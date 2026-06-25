# Copyright 2025 Open Source Robotics Foundation, Inc.
# Licensed under the Apache License, Version 2.0

from collections import defaultdict
import os
from pathlib import Path

from packaging.version import Version
from pallet_patcher.manifest import get_dependencies
from pallet_patcher.manifest import load_manifest
from pallet_patcher.solver import solve_dependency


def _get_available_crates(search_path):
    """
    Create a list of crates available from a directory.

    :param search_path: Local registry source to search for packages
    :type search_path: Path

    :returns: Collection of pkgs available in a directory and their versions
    :rtype: dict

    :returns: Collection of the directory and metadata information for a
              specific pkgname+version
    :rtype: dict
    """
    manifest_paths = search_path.glob('*/Cargo.toml')
    return _get_crates(manifest_paths)


def _get_crates(manifest_paths):
    versions = defaultdict(set)  # Skip duplicates in versions dict
    pkgs_metadata = {}

    # Iterate over all the manifests provided
    for manifest_path in manifest_paths:
        manifest = load_manifest(manifest_path)
        pkgname = manifest.get('package', {}).get('name')
        # TO-DO: In some cases, we want to crash if we can't find the package
        if not pkgname:
            continue
        version_manifest = manifest.get(
            'package', {}).get('version') or '0.0.0'
        version = str(Version(version_manifest))

        versions[pkgname].add(version)

        # We are assuming here there won't be duplicated crates+version within
        # the same search_path.
        pkgs_metadata[f'{pkgname}::{version}'] = (
            manifest_path.parent, manifest)

    return versions, pkgs_metadata


def _get_reference(specification):
    if not isinstance(specification, dict):
        return None
    path = specification.get('path')
    if path is not None:
        return Path(path).as_uri()
    git = specification.get('git')
    if git is not None:
        return git
    return specification.get('registry')


def compose(dependencies, search_paths, *, seeds=None):
    """
    Compose a collection of crates which may satisfy given dependencies.

    :param dependencies: List of dependency tuples
      (import name, specifications)
    :type dependencies: tuple
    :param search_paths: List of local registry sources to search for packages
    :type search_paths: list
    :param seeds: List of package directories which are explicit candidates for
      composition.
    :type seeds: list

    :returns: Collection of packages which may satisfy the required
      dependencies.
    :rtype: dict
    """
    dependency_paths_registered = []
    if seeds:
        manifest_paths = [seed / 'Cargo.toml' for seed in seeds]
        crates_and_metadata = _get_crates(manifest_paths)
        dependency_paths_registered.append(crates_and_metadata)

    for user_path in search_paths:
        crates_and_metadata = _get_available_crates(user_path)
        dependency_paths_registered.append(crates_and_metadata)

    composition = {}
    solved_specifiers = {}

    queue = list(dependencies)
    while queue:
        name, specifications = queue.pop(0)
        if isinstance(specifications, dict):
            # This case covers packages like: rustc-std-workspace-core
            # where it's listed name differs from the installation name
            # print(name, specification)
            # core {'version': '1.0.0',
            #    'optional': True, 'package': 'rustc-std-workspace-core'}
            name = specifications.get('package', name)
            version_spec = specifications.get('version', '*')
        else:
            version_spec = specifications

        # If we already parsed a version_spec, do not repeat that
        # TO-DO: this won't filter libc==0.2.62, libc==0.2.95, etc
        if name+str(version_spec) in solved_specifiers:
            continue

        candidate = None
        # Priority mechanism, check the dependency paths in the order provided
        for crates, metadada in dependency_paths_registered:
            if crates[name]:
                solved_version = solve_dependency(version_spec, crates[name])
                if solved_version:
                    candidate = metadada[f'{name}::{solved_version}']
                    break

        # Do not search again for versions specifiers that we already looked up
        solved_specifiers[name+str(version_spec)] = True

        if candidate is None:
            # We rely on cargo to pull from its default registry (crates.io)
            # if we don't find a dependency locally.
            # TO-DO(blast545): This might throw an error if we use
            # pallet-patcher for auditing reasons.
            continue

        reference = _get_reference(specifications)
        # Add the dependencies of the pkg to the list of packages that we
        # need to find afterwards
        location, manifest = candidate
        plain_deps, build_deps, _ = get_dependencies(manifest, location)
        queue.extend(plain_deps.items())
        queue.extend(build_deps.items())

        # We also add the raw pkgname to the composition, because patches
        # don't support adding pkgname+version as part of the patch name
        composition[name+'::'+solved_version] = (reference, location, name)

    return composition


def get_cargo_arguments(composition, default_registry=None):
    """
    Get arguments to pass to 'cargo' which patch package references.

    :param composition: The curated package composition
    :type composition: dict
    :param default_registry: The default package registry if none was specified
    :type default_registry: str, optional

    :returns: List of command line arguments
    :rtype: list
    """
    if default_registry is None:
        default_registry = os.environ.get('CARGO_REGISTRY_DEFAULT')
        if not default_registry:
            default_registry = 'crates-io'
    arguments = set()
    for versioned_name, (reference, candidate, pkgname) in composition.items():
        # I'm not sure how this will work with user custom references here
        if not reference:
            reference = default_registry
        elif candidate.as_uri() == reference:
            # Cargo does not allow a patch to point to the same location as
            # the original dependency specification. If we encounter this,
            # just skip the reference entirely since it already points to
            # at least one of our candidates.
            continue

        section = f"patch.'{reference}'.'{versioned_name}'"
        arguments.add(f"--config={section}.package='{pkgname}'")
        arguments.add(f"--config={section}.path='{candidate}'")
    return sorted(arguments)


def get_cargo_config(composition, default_registry=None):
    """
    Get Cargo configuration to patch package references.

    :param composition: The curated package composition
    :type composition: dict
    :param default_registry: The default package registry if none was specified
    :type default_registry: str, optional

    :returns: Raw TOML configuration
    :rtype: str
    """
    if default_registry is None:
        default_registry = os.environ.get('CARGO_REGISTRY_DEFAULT')
        if not default_registry:
            default_registry = 'crates-io'
    sections = set()
    for versioned_name, (reference, candidate, pkgname) in composition.items():
        if reference is None:
            reference = default_registry
        elif candidate.as_uri() == reference:
            # Cargo does not allow a patch to point to the same location as
            # the original dependency specification. If we encounter this,
            # just skip the reference entirely since it already points to
            # at least one of our candidates.
            continue

        sections.add('\n'.join((
            f"[patch.'{reference}'.'{versioned_name}']",
            f"package = '{pkgname}'",
            f"path = '{candidate}'",
        )))
    return '\n\n'.join(sorted(sections))
