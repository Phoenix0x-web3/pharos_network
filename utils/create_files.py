import os
import shutil
from copy import deepcopy

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

from data.config import FILES_DIR, SETTINGS_FILE, TEMPLATE_SETTINGS_FILE
from libs.eth_async.utils.files import touch

REQUIRED_FILES = [
    "private_keys.txt",
    "proxy.txt",
    "twitter_tokens.txt",
    "discord_tokens.txt",
    "discord_proxy.txt",
]


def create_files() -> None:
    touch(path=FILES_DIR)
    for name in REQUIRED_FILES:
        touch(path=os.path.join(FILES_DIR, name), file=True)
    create_yaml()


def load_yaml_file(path: str) -> CommentedMap:
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.explicit_start = True
    yaml.explicit_end = True
    if not os.path.exists(path):
        return CommentedMap()
    try:
        with open(path, "r", encoding="utf-8") as f:
            loaded = yaml.load(f)
            return loaded or CommentedMap()
    except Exception:
        return CommentedMap()


def create_yaml():
    yaml = YAML()
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.preserve_quotes = True
    yaml.explicit_start = True
    yaml.explicit_end = True
    template_settings = load_yaml_file(TEMPLATE_SETTINGS_FILE)
    current_settings = load_yaml_file(SETTINGS_FILE)
    updated_settings = merge_settings(current_settings, template_settings)
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        yaml.dump(updated_settings, f)


def merge_settings(current: CommentedMap, template: CommentedMap) -> CommentedMap:
    result = CommentedMap()

    if hasattr(template, "ca") and getattr(template.ca, "comment", None) and template.ca.comment:
        comment_text = ""
        for comment_item in template.ca.comment:
            if isinstance(comment_item, list):
                for sub_item in comment_item:
                    if sub_item and hasattr(sub_item, "value"):
                        comment_text += sub_item.value
            elif comment_item and hasattr(comment_item, "value"):
                comment_text += comment_item.value
        if comment_text.strip():
            result.yaml_set_start_comment(comment_text)

    for key in template.keys():
        if key not in current:
            result[key] = deepcopy(template[key])
        elif isinstance(template[key], dict) and isinstance(current[key], dict):
            result[key] = merge_settings(current[key], template[key])
        else:
            result[key] = current[key]

        if hasattr(template, "ca") and key in template.ca.items and template.ca.items[key][2]:
            result.ca.items[key] = deepcopy(template.ca.items[key])

    for key in current.keys():
        if key not in template:
            result[key] = current[key]
            if hasattr(current, "ca") and key in current.ca.items:
                result.ca.items[key] = deepcopy(current.ca.items[key])

    return result


def reset_folder():
    shutil.rmtree(FILES_DIR)
    create_files()


create_files()
