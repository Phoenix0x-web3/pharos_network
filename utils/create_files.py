from data.config import FILES_DIR, SETTINGS_FILE, TEMPLATE_SETTINGS_FILE
from libs.eth_async.utils.files import touch
import os
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.util import load_yaml_guess_indent
from copy import deepcopy

REQUIRED_FILES = [
    "privatekeys.txt",
    "proxy.txt",
    "twitter_tokens.txt",
    "discord_tokens.txt",
]

def create_files() -> None:
    touch(path=FILES_DIR)
    for name in REQUIRED_FILES:
        touch(path=os.path.join(FILES_DIR, name), file=True)
    create_yaml()

def create_yaml():
    yaml = YAML()
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.preserve_quotes = True
    template_settings = load_yaml_file(TEMPLATE_SETTINGS_FILE)
    current_settings = load_yaml_file(SETTINGS_FILE)
    updated_settings = merge_settings(current_settings, template_settings)
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        yaml.dump(updated_settings, f)

def load_yaml_file(path: str) -> CommentedMap:
    if not os.path.exists(path):
        return CommentedMap()
    with open(path, "r", encoding="utf-8") as f:
        loaded, _, _ = load_yaml_guess_indent(f)
        return loaded or CommentedMap()

def merge_settings(current: CommentedMap, template: CommentedMap) -> CommentedMap:
    for key, value in template.items():
        if key not in current:
            current[key] = deepcopy(value)
            if hasattr(template, 'ca') and key in template.ca.items:
                if not hasattr(current, 'ca'):
                    current.ca = type(template.ca)()
                current.ca.items[key] = template.ca.items[key]

        elif isinstance(value, dict) and isinstance(current[key], dict):
            current[key] = merge_settings(current[key], value)

        elif hasattr(template, 'ca') and key in template.ca.items:
            t_comment = template.ca.items[key]
            c_comment = current.ca.items.get(key) if hasattr(current, 'ca') else None
            if t_comment != c_comment:
                if not hasattr(current, 'ca'):
                    current.ca = type(template.ca)()
                current.ca.items[key] = t_comment

    if hasattr(template, 'ca') and getattr(template.ca, 'comment', None):
        if not hasattr(current, 'ca'):
            current.ca = type(template.ca)()
        if not getattr(current.ca, 'comment', None):
            current.ca.comment = template.ca.comment

    return current

create_files()
