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


def build_index(seeds, search_paths):
    """
    Build the priority-ordered crate index used to resolve dependencies.

    :param seeds: List of package directories which are explicit candidates.
    :type seeds: list
    :param search_paths: List of local registry sources to search for packages
    :type search_paths: list

    :returns: List of (versions, metadata) pairs in priority order
    :rtype: list
    """
    registered = []
    if seeds:
        manifest_paths = [seed / 'Cargo.toml' for seed in seeds]
        registered.append(_get_crates(manifest_paths))

    for user_path in search_paths:
        registered.append(_get_available_crates(user_path))

    return registered


def get_vendored_registry(location):
    """
    Get the crates a package ships vendored alongside its own manifest.

    A package which cannot source a dependency from the platform ships it in a
    'vendor' directory next to its manifest, as produced by 'cargo vendor'.
    That directory holds the package's whole transitive closure, flattened.

    :param location: Directory the package's manifest resides in
    :type location: Path

    :returns: Crates the package vendored, or None when it vendored none
    :rtype: tuple or None
    """
    vendor_path = location / 'vendor'
    if not vendor_path.is_dir():
        return None
    return _get_available_crates(vendor_path)


def derive_name_and_spec(name, specifications):
    """
    Resolve the crate name and version specifier for a dependency entry.

    :param name: The import name the dependency is listed under
    :type name: str
    :param specifications: The dependency's specification
    :type specifications: str or dict

    :returns: Tuple of (crate name, version specifier)
    :rtype: tuple
    """
    if isinstance(specifications, dict):
        # This case covers packages like: rustc-std-workspace-core
        # where its listed name differs from the installation name
        # core {'version': '1.0.0',
        #    'optional': True, 'package': 'rustc-std-workspace-core'}
        return specifications.get('package', name), \
            specifications.get('version', '*')
    return name, specifications


def find_candidate(name, version_spec, registered):
    """
    Find the highest-priority local crate satisfying a dependency.

    :param name: The crate name to look up
    :type name: str
    :param version_spec: The version specifier to satisfy
    :type version_spec: str
    :param registered: Priority-ordered crate index from :func:`build_index`
    :type registered: list

    :returns: Tuple of (solved version, (directory, manifest)) or None
    :rtype: tuple
    """
    # Priority mechanism, check the dependency paths in the order provided
    for crates, metadata in registered:
        available_versions = crates.get(name)
        if available_versions:
            solved_version = solve_dependency(version_spec, available_versions)
            if solved_version:
                return solved_version, metadata[f'{name}::{solved_version}']
    return None


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
    registered = build_index(seeds, search_paths)

    composition = {}
    solved_specifiers = {}

    # Each entry carries the single vendored registry in scope for it, if any,
    # see the subtree handling below
    queue = [(name, spec, None) for name, spec in dependencies]
    while queue:
        name, specifications, vendored = queue.pop(0)
        name, version_spec = derive_name_and_spec(name, specifications)

        # If we already parsed a version_spec, do not repeat that
        # TO-DO: this won't filter libc==0.2.62, libc==0.2.95, etc
        if name+str(version_spec) in solved_specifiers:
            continue

        # Do not search again for versions specifiers that we already looked up
        solved_specifiers[name+str(version_spec)] = True

        # Fall back to the vendored registry of the crate this dependency
        # belongs to, and only that one, so a crate from a search path still
        # wins and one package's vendored copies cannot satisfy another's
        if vendored is None:
            index = registered
        else:
            index = [*registered, vendored]

        found = find_candidate(name, version_spec, index)
        if found is None:
            # We rely on cargo to pull from its default registry (crates.io)
            # if we don't find a dependency locally.
            # TO-DO(blast545): This might throw an error if we use
            # pallet-patcher for auditing reasons.
            continue

        solved_version, (location, manifest) = found
        reference = _get_reference(specifications)
        # Add the dependencies of the pkg to the list of packages that we
        # need to find afterwards
        plain_deps, build_deps, _ = get_dependencies(manifest, location)

        # A crate which vendored its dependencies supplies them to everything
        # below it, because 'cargo vendor' flattens the whole transitive
        # closure into one directory. A crate which vendored none keeps
        # resolving against whatever its parent was using
        crate_vendored = get_vendored_registry(location)
        subtree = crate_vendored if crate_vendored is not None else vendored

        queue.extend((n, s, subtree) for n, s in plain_deps.items())
        queue.extend((n, s, subtree) for n, s in build_deps.items())

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
