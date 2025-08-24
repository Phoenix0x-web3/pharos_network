from typing import Optional, Any
from datetime import datetime, timedelta

from pydantic import BaseModel, Field, field_validator

from .utils import to_datetime, tweet_url


class Image(BaseModel):
    type: str = Field(..., alias="image_type")
    width: int = Field(..., alias="w")
    height: int = Field(..., alias="h")


class Media(BaseModel):
    id: int = Field(..., alias="media_id")
    image: Image
    size: int
    expires_at: datetime = Field(..., alias="expires_after_secs")

    @field_validator("expires_at", mode="before")
    @classmethod
    def set_expires_at(cls, v):
        return datetime.now() + timedelta(seconds=v)

    def __str__(self):
        return str(self.id)

    def __hash__(self):
        return hash(self.id)


class User(BaseModel):
    # fmt: off
    id:              int      | None = None
    username:        str      | None = None
    name:            str      | None = None  # 50
    created_at:      datetime | None = None
    description:     str      | None = None  # 160
    location:        str      | None = None  # 30
    followers_count: int      | None = None
    friends_count:   int      | None = None
    raw_data:        dict     | None = None
    # fmt: on

    def __str__(self):
        return str(self.id)

    def __repr__(self):
        return f"{self.__class__.__name__}(id={self.id}, username={self.username})"

    def __hash__(self):
        return hash(self.id)

    @classmethod
    def from_raw_data(cls, data: dict):
        legacy = data.get("legacy") or {}  
        keys = ("description", "followers_count", "friends_count")

        values = {key: legacy.get(key) for key in keys}
        values.update(
            {
                "id": int(data.get("rest_id", 0)),
                "username": legacy.get("screen_name", ""),
                # "created_at": to_datetime(legacy.get("created_at")),
                "raw_data": data,
            }
        )
        return cls(**values)


class Tweet(BaseModel):
    # fmt: off
    id:              int
    text:            str
    language:        str
    created_at:      datetime

    conversation_id: int

    quoted:          bool
    retweeted:       bool
    bookmarked:      bool
    favorited:       bool

    quote_count:     int
    retweet_count:   int
    bookmark_count:  int
    favorite_count:  int
    reply_count:     int

    quoted_tweet:    Optional["Tweet"] = None
    retweeted_tweet: Optional["Tweet"] = None

    user:            User
    url:             str

    raw_data:        dict

    # TODO hashtags
    # TODO media
    # TODO symbols
    # TODO timestamps
    # TODO urls
    # TODO user_mentions
    # TODO views
    # fmt: on

    def __str__(self):
        return str(self.id)

    def __repr__(self):
        return f"{self.__class__.__name__}(id={self.id}, user_id={self.user.id})"

    def __hash__(self):
        return hash(self.id)

    @property
    def short_text(self) -> str:
        return f"{self.text[:32]}..." if len(self.text) > 16 else self.text

    @classmethod
    def from_raw_data(cls, data: dict):
        legacy_data = data.get("legacy") or {}
        if not legacy_data:
            # No legacy data — you can either return None or raise an exception
            return None

        user_data = (
            data.get("core", {})
            .get("user_results", {})
            .get("result", {})
        )
        user = User.from_raw_data(user_data) if user_data else None

        id = int(legacy_data.get("id_str", 0))
        url = tweet_url(user.username if user else None, id)

        retweeted_tweet = None
        if "retweeted_status_result" in legacy_data:
            retweeted_tweet_data = legacy_data["retweeted_status_result"].get("result")
            if retweeted_tweet_data:
                retweeted_tweet = cls.from_raw_data(retweeted_tweet_data)

        quoted_tweet = None
        if "quoted_status_result" in data:
            quoted_tweet_data = data["quoted_status_result"].get("result")
            if quoted_tweet_data:
                quoted_tweet = cls.from_raw_data(quoted_tweet_data)

        values = {
            "id": id,
            "text": legacy_data.get("full_text"),
            "language": legacy_data.get("lang"),
            "created_at": to_datetime(legacy_data.get("created_at")) if legacy_data.get("created_at") else None,
            "conversation_id": int(legacy_data.get("conversation_id_str", 0)),
            "quoted": legacy_data.get("is_quote_status", False),
            "retweeted": legacy_data.get("retweeted", False),
            "bookmarked": legacy_data.get("bookmarked", False),
            "favorited": legacy_data.get("favorited", False),
            "quote_count": legacy_data.get("quote_count", 0),
            "retweet_count": legacy_data.get("retweet_count", 0),
            "bookmark_count": legacy_data.get("bookmark_count", 0),
            "favorite_count": legacy_data.get("favorite_count", 0),
            "reply_count": legacy_data.get("reply_count", 0),
            "user": user.model_dump() if user else None,
            "quoted_tweet": quoted_tweet.model_dump() if quoted_tweet else None,
            "retweeted_tweet": retweeted_tweet.model_dump() if retweeted_tweet else None,
            "url": url,
            "raw_data": data,
        }
        return cls(**values)


class Subtask(BaseModel):
    id: str
    primary_text: Optional[str] = None
    secondary_text: Optional[str] = None
    detail_text: Optional[str] = None
    raw_data: dict

    def __hash__(self):
        return hash(self.id)

    @classmethod
    def from_raw_data(cls, data: dict) -> "Subtask":
        task = {"id": data["subtask_id"]}
        if enter_text := data.get("enter_text"):
            if header := enter_text.get("header"):
                if primary_text := header.get("primary_text"):
                    task["primary_text"] = primary_text["text"]
                if secondary_text := header.get("secondary_text"):
                    task["secondary_text"] = secondary_text["text"]
                if detail_text := header.get("detail_text"):
                    task["detail_text"] = detail_text["text"]
        return cls(**task, raw_data=data)
