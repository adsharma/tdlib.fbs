#!/usr/bin/env python3

#  Pyrogram - Telegram MTProto API Client Library for Python
#  Copyright (C) 2017-2020 Dan <https://github.com/delivrance>
#
#  This file is part of Pyrogram.
#
#  Pyrogram is free software: you can redistribute it and/or modify
#  it under the terms of the GNU Lesser General Public License as published
#  by the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  Pyrogram is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU Lesser General Public License for more details.
#
#  You should have received a copy of the GNU Lesser General Public License
#  along with Pyrogram.  If not, see <http://www.gnu.org/licenses/>.

import argparse
import re
from collections import defaultdict
from functools import partial
from pathlib import Path
from typing import List, Tuple
from jinja2 import Environment, FileSystemLoader
from dataclasses import dataclass

# from autoflake import fix_code
# from black import format_str, FileMode

HOME_PATH = Path("compiler/api")

SECTION_RE = re.compile(r"---(\w+)---")
LAYER_RE = re.compile(r"//\sLAYER\s(\d+)")
COMBINATOR_RE = re.compile(
    r"^([\w.]+)(#[0-9a-f]+)?\s(?:.*)=\s([\w<>.]+);$", re.MULTILINE
)
ARGS_RE = re.compile(r"[^{](\w+):([\w?!.<>#]+)")
FLAGS_RE = re.compile(r"flags\.(\d+)\?")
FLAGS_RE_2 = re.compile(r"flags\.(\d+)\?([\w<>.]+)")
FLAGS_RE_3 = re.compile(r"flags:#")
INT_RE = re.compile(r"int(\d+)")

CORE_TYPES = [
    "int",
    "long",
    "int128",
    "int256",
    "double",
    "bytes",
    "string",
    "Bool",
    "true",
]

WARNING = """
# # # # # # # # # # # # # # # # # # # # # # # #
#               !!! WARNING !!!               #
#          This is a generated file!          #
# All changes made in this file will be lost! #
# # # # # # # # # # # # # # # # # # # # # # # #
""".strip()

# noinspection PyShadowingBuiltins
open = partial(open, encoding="utf-8")

types_to_constructors = {}
types_to_functions = {}
constructors_to_functions = {}
namespaces_to_types = {}
namespaces_to_constructors = {}
namespaces_to_functions = {}


@dataclass
class Combinator:
    section: str
    qualname: str
    namespace: str
    name: str
    id: str
    has_flags: bool
    flags: List[str]
    args: List[Tuple[str, str]]
    qualtype: str
    typespace: str
    type: str


def snake(s: str):
    # https://stackoverflow.com/q/1175208
    s = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", s)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s).lower()


def camel(s: str):
    return "".join([i[0].upper() + i[1:] for i in s.split("_")])


# noinspection PyShadowingBuiltins, PyShadowingNames
def get_type_hint(type: str) -> str:
    is_flag = FLAGS_RE.match(type)

    if is_flag:
        type = type.split("?")[1]

    if type in CORE_TYPES:
        if type in ["Bool", "true"]:
            type = "bool"
        elif type == "bytes":
            type = "[byte]"

    if re.match("^vector", type, re.I):
        sub_type = type.split("<")[1][:-1]
        type = f"[{get_type_hint(sub_type)}]"

    return f"{type}"


def sort_args(args):
    """Put flags at the end"""
    args = args.copy()
    flags = [i for i in args if FLAGS_RE.match(i[1])]

    for i in flags:
        args.remove(i)

    try:
        args.remove(("flags", "#"))
    except ValueError:
        pass

    return (args, flags)


def remove_whitespaces(source: str) -> str:
    """Remove whitespaces from blank lines"""
    lines = source.split("\n")

    for i, _ in enumerate(lines):
        if re.match(r"^\s+$", lines[i]):
            lines[i] = ""

    return "\n".join(lines)


# noinspection PyShadowingBuiltins
def start(fname: Path, core: str):

    with open(Path(".") / fname) as f:
        schema = (f.read()).splitlines()

    section = None
    layer = None
    combinators = []

    for line in schema:
        # Check for section changer lines
        section_match = SECTION_RE.match(line)
        if section_match:
            section = section_match.group(1)
            continue

        # Save the layer version
        layer_match = LAYER_RE.match(line)
        if layer_match:
            layer = layer_match.group(1)
            continue

        combinator_match = COMBINATOR_RE.match(line)
        if combinator_match:
            # noinspection PyShadowingBuiltins
            qualname, id, qualtype = combinator_match.groups()

            namespace, name = qualname.split(".") if "." in qualname else ("", qualname)
            name = camel(name)
            qualname = ".".join([namespace, name]).lstrip(".")

            typespace, type = qualtype.split(".") if "." in qualtype else ("", qualtype)
            type = camel(type)
            qualtype = ".".join([typespace, type]).lstrip(".")

            # Pingu!
            has_flags = not not FLAGS_RE_3.findall(line)

            args = ARGS_RE.findall(line)

            # Fix arg name being "self" (reserved python keyword)
            for i, item in enumerate(args):
                if item[0] == "self":
                    args[i] = ("is_self", item[1])

            combinator = Combinator(
                section=section,
                qualname=qualname,
                namespace=namespace,
                name=name,
                id=f"0x{id}",
                has_flags=has_flags,
                flags=[],
                args=args,
                qualtype=qualtype,
                typespace=typespace,
                type=type,
            )

            combinators.append(combinator)

    for c in combinators:
        qualtype = c.qualtype

        if qualtype.startswith("Vector"):
            qualtype = qualtype.split("<")[1][:-1]

        d = types_to_constructors if c.section == "types" or c.section is None else types_to_functions

        if qualtype not in d:
            d[qualtype] = []

        d[qualtype].append(c.qualname)

        if c.section == "types":
            key = c.namespace

            if key not in namespaces_to_types:
                namespaces_to_types[key] = []

            if c.type not in namespaces_to_types[key]:
                namespaces_to_types[key].append(c.type)

    for k, v in types_to_constructors.items():
        for i in v:
            try:
                constructors_to_functions[i] = types_to_functions[k]
            except KeyError:
                pass

    # import json
    # print(json.dumps(namespaces_to_types, indent=2))

    groups = defaultdict(list)
    unions = defaultdict(list)
    for c in combinators:
        sorted_args, c.flags = sort_args(c.args)

        def split_flag(v):
            num, subtype = re.split(FLAGS_RE, v)[1:]
            subtype = get_type_hint(subtype)
            return (num, subtype)

        c.flags = [(k, split_flag(v)) for k, v in c.flags]
        c.flags = sorted(c.flags, key=lambda flag: int(flag[1][0]))

        arguments = [(k, get_type_hint(v)) for k, v in sorted_args]
        if c.section == "types" or c.section is None:
            out = c.qualname.split(".")
            if len(out) == 2:
                group, name = out
            else:
                group, name = core, c.qualname
            groups[group].append({name: (c, arguments)})

    for name, subtypes in types_to_constructors.items():
        out = name.split(".")
        if len(out) == 2:
            group, name = out
        else:
            group, name = core, name
        if len(subtypes) == 1 and subtypes[0] == name:
            continue
        unions[group].append({name: subtypes})

    for group in groups:
        file_loader = FileSystemLoader("templates")
        env = Environment(loader=file_loader)

        template = env.get_template("template.fbs.j2")

        output = template.render(types=groups[group], unions=unions[group])
        with open(f"{group}.fbs", "w+") as f:
            f.write(output)


if "__main__" == __name__:
    parser = argparse.ArgumentParser()
    parser.add_argument("-v", "--verbose", help="verbose logging")
    parser.add_argument("-c", "--core", help="output filename for core types", default="core")
    args, rest = parser.parse_known_args()
    HOME_PATH = Path(".")
    for fname in rest:
        start(Path(fname), core=args.core)
