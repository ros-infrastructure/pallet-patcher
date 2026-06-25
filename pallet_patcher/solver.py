# Copyright 2025 Open Source Robotics Foundation, Inc.
# Licensed under the Apache License, Version 2.0

from typing import Collection

from packaging.specifiers import SpecifierSet
from packaging.version import Version


def _parse_cargo_specifier(spec_str: str) -> SpecifierSet:
    clean_spec = spec_str.strip()

    # 1. Handle "Explicit Equals" (=1.2.3 -> ==1.2.3)
    if clean_spec.startswith('=') and not clean_spec.startswith('=='):
        # Strip just in case there are spaces like "= 1.2"
        version_part = clean_spec[1:].strip()
        parts = version_part.split('.')

        # If it's missing the minor or patch version,
        # Cargo treats it as a wildcard
        if len(parts) < 3:
            return SpecifierSet(f'=={version_part}.*')
        else:
            return SpecifierSet(f'=={version_part}')

    # 2. Handle Tilde (~1.2.3) - Minimal update
    if clean_spec.startswith('~'):
        version_part = clean_spec.lstrip('~')
        parts = version_part.split('.')
        try:
            if len(parts) >= 2:
                major, minor = int(parts[0]), int(parts[1])
                return SpecifierSet(f'>={version_part},<{major}.{minor + 1}.0')
            elif len(parts) == 1:
                major = int(parts[0])
                return SpecifierSet(f'>={version_part},<{major + 1}.0.0')
        except ValueError:
            pass

    # 3. Handle Caret (^1.2.3) - Maximal update (Compatible)
    # Rust: ^1.2.3 is the same as 1.2.3 (it's the default)
    # We strip the caret and let it fall through to the "Bare" logic below.
    if clean_spec.startswith('^'):
        clean_spec = clean_spec[1:]

    # 4. Handle "Bare" / Caret versions
    if clean_spec and clean_spec[0].isdigit() and '*' not in clean_spec:
        parts = clean_spec.split('.')
        try:
            major = int(parts[0])

            # Case A: Major > 0 (e.g. ^1.2.3) -> Lock Major
            if major > 0:
                return SpecifierSet(f'>={clean_spec},<{major + 1}.0.0')

            # Case B: Major is 0
            if major == 0:
                # Case B.1: Single digit (^0) -> Allow 0.x.x
                if len(parts) == 1:
                    return SpecifierSet(f'>={clean_spec},<1.0.0')

                minor = int(parts[1])

                # Case B.2: Major 0, Minor > 0 (e.g. ^0.2.3) -> Lock Minor
                if minor > 0:
                    return SpecifierSet(f'>={clean_spec},<0.{minor + 1}.0')

                # Case B.3: Major 0, Minor 0 (e.g. ^0.0.3) -> Lock Patch
                # In Rust, 0.0.x changes are always breaking.
                elif minor == 0 and len(parts) > 2:
                    patch = int(parts[2])
                    return SpecifierSet(f'>={clean_spec},<0.0.{patch + 1}')

                # Case B.4: ^0.0 (Implies 0.0.x)
                elif minor == 0:
                    return SpecifierSet(f'>={clean_spec},<0.1.0')

        except ValueError:
            pass

    # 5. Handle purely *
    if clean_spec == '*':
        return SpecifierSet('>=0.0.0')

    # 6. Match comparison operators and wildcards
    comparison_op = ''
    for maybe_op in ('<=', '>=', '<', '>'):
        if clean_spec.startswith(maybe_op):
            comparison_op = maybe_op
            break

    # Isolate base version and check for wildcards
    base_version = clean_spec[len(comparison_op):].strip()
    is_wildcard = base_version.endswith('.*')

    if is_wildcard:
        base_version = base_version[:-2]  # Strip '.*'

    parts = base_version.split('.')
    is_partial = len(parts) < 3

    # 4. Process directional comparisons (<, <=, >, >=) with partials/wildcards
    if comparison_op in ('<', '<=', '>', '>='):
        if is_wildcard or is_partial:
            if comparison_op == '<=':
                try:
                    parts[-1] = str(int(parts[-1]) + 1)
                    return SpecifierSet(f"<{'.'.join(parts)}")
                except ValueError:
                    pass
            elif comparison_op == '<':
                return SpecifierSet(f'<{base_version}')
            elif comparison_op == '>=':
                return SpecifierSet(f'>={base_version}')
            elif comparison_op == '>':
                try:
                    parts[-1] = str(int(parts[-1]) + 1)
                    return SpecifierSet(f'>={".".join(parts)}')
                except ValueError:
                    pass
        return SpecifierSet(f'{comparison_op}{base_version}')

    if not comparison_op and is_wildcard:
        # Bare wildcards like '0.4.*' translate to '==0.4.*'
        return SpecifierSet(f'=={base_version}.*')

    # Fallback for standard Python specifiers (if anything not covered)
    return SpecifierSet(clean_spec)


def _parse_cargo_specifiers(spec_str: str) -> Collection[SpecifierSet]:
    return tuple(map(_parse_cargo_specifier, spec_str.split(',')))


def solve_dependency(version_specifier, available_versions):
    """
    Find if ver available in versions_dict matches the expected spec provided.

    :param version_spec: Specifier for the version we want to match.
    :type version_spec: str

    :param available_versions: List of versions available.
    :type available_versions: str

    :returns: matched version string, or None if available ver don't match
    :rtype: dict
    """
    specs = _parse_cargo_specifiers(version_specifier)

    # We sort them first to prioritize higher versions for the packages
    sorted_versions = sorted(
        available_versions,
        key=Version,
        reverse=True
    )

    # Iterate over the sorted list
    for version in sorted_versions:
        v = Version(version)
        # print(v, spec)
        if all(v in spec for spec in specs):
            return str(v)

    return None
