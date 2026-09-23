# Copyright 2025 Open Source Robotics Foundation, Inc.
# Licensed under the Apache License, Version 2.0

from pathlib import Path
import shutil
import subprocess

from pallet_patcher.command import load_and_compose
from pallet_patcher.search import compose
from pallet_patcher.search import get_cargo_arguments
from pallet_patcher.search import get_cargo_config
import pytest

_PACKAGES_PATH = Path(__file__).parent / 'packages'

_CARGO = shutil.which('cargo')


def test_dry():
    dependencies = [
        ('pkg-e', '*'),
    ]
    search_paths = (
        _PACKAGES_PATH / 'upper_layer',
        _PACKAGES_PATH / 'lower_layer',
    )

    composition = compose(dependencies, search_paths)
    assert len(composition) == 5, f'{composition}'

    # We expect 2 arguments per element in the composition
    # Since the versioned version understand that we only need one
    # of the versions of pkg-a, we only have 8 arguments
    arguments = get_cargo_arguments(composition)
    assert len(arguments) == 8, f'{arguments}'

    config = get_cargo_config(composition)
    assert config


@pytest.mark.skipif(not _CARGO, reason='The cargo executable is not available')
def test_cargo_arguments(tmpdir):
    layer_src = _PACKAGES_PATH / 'upper_layer'
    layer_dst = Path(tmpdir) / 'upper_layer'
    shutil.copytree(str(layer_src), layer_dst)

    search_paths = (
        layer_dst,
        _PACKAGES_PATH / 'lower_layer',
    )

    pkg_e = layer_dst / 'pkg-e-0.0.0'
    composition = load_and_compose(pkg_e / 'Cargo.toml', search_paths)
    arguments = get_cargo_arguments(composition)

    subprocess.run(
        [_CARGO, 'metadata', '--format-version=1', '--offline', *arguments],
        cwd=str(pkg_e),
        check=True)


@pytest.mark.skipif(not _CARGO, reason='The cargo executable is not available')
def test_cargo_config(tmpdir):
    layer_src = _PACKAGES_PATH / 'upper_layer'
    layer_dst = Path(tmpdir) / 'upper_layer'
    shutil.copytree(str(layer_src), layer_dst)

    search_paths = (
        layer_dst,
        _PACKAGES_PATH / 'lower_layer',
    )

    pkg_e = layer_dst / 'pkg-e-0.0.0'
    composition = load_and_compose(pkg_e / 'Cargo.toml', search_paths)
    config = get_cargo_config(composition)

    config_file = pkg_e / '.cargo' / 'config.toml'
    config_file.parent.mkdir()
    config_file.write_text(config)

    subprocess.run(
        [_CARGO, 'metadata', '--format-version=1', '--offline'],
        cwd=str(pkg_e),
        check=True)


def test_different_versions_same_folder():
    """Two different version specs of pkg-a resolve to distinct entries."""
    # pkg-f depends on pkg-a =1.0.0 directly, and on pkg-b which
    # depends on pkg-a * (resolves to 1.1.0). Both versions live
    # in lower_layer.
    # TO-DO: once dedup checks whether an already-resolved version
    # satisfies the new spec, '*' should reuse the existing 1.0.0
    # and this test should expect 1 pkg-a entry instead.
    dependencies = [
        ('pkg-f', '*'),
    ]
    search_paths = (
        _PACKAGES_PATH / 'lower_layer',
    )

    composition = compose(dependencies, search_paths)

    pkg_a_entries = {
        k: v for k, v in composition.items() if v[2] == 'pkg-a'
    }
    assert len(pkg_a_entries) == 2, \
        f'Expected 2 pkg-a entries, got {pkg_a_entries}'
    assert 'pkg-a::1.0.0' in composition
    assert 'pkg-a::1.1.0' in composition


def test_different_versions_across_folders():
    """Version resolution works across multiple search paths."""
    # Same scenario but search_paths spans both layers.
    # pkg-a only lives in lower_layer, so both versions should
    # still resolve from there.
    dependencies = [
        ('pkg-f', '*'),
    ]
    search_paths = (
        _PACKAGES_PATH / 'upper_layer',
        _PACKAGES_PATH / 'lower_layer',
    )

    composition = compose(dependencies, search_paths)

    pkg_a_entries = {
        k: v for k, v in composition.items() if v[2] == 'pkg-a'
    }
    assert len(pkg_a_entries) == 2, \
        f'Expected 2 pkg-a entries, got {pkg_a_entries}'


def test_same_version_spec_deduplicates():
    """Identical version specs for the same crate produce only one entry."""
    # pkg-e has pkg-a as a dev-dep with '*', and transitively via
    # pkg-b which also depends on pkg-a '*'. Same spec = one entry.
    dependencies = [
        ('pkg-e', '*'),
    ]
    search_paths = (
        _PACKAGES_PATH / 'upper_layer',
        _PACKAGES_PATH / 'lower_layer',
    )

    composition = compose(dependencies, search_paths)

    pkg_a_entries = [
        k for k in composition if composition[k][2] == 'pkg-a'
    ]
    assert len(pkg_a_entries) == 1, \
        f'Expected 1 pkg-a entry (deduplicated), got {pkg_a_entries}'


def test_pkgname_with_prerelease_works():
    """Pre-release packages are properly parsed."""
    # This failed because _get_crates was saving versions without
    # a Version() conversion and later on resolved dependencies
    # by sorting them based on Version objects rather on saved streams
    # 0.11.1+wasi-snapshot-preview1 -> 0.11.1+wasi.snapshot.preview1
    dependencies = [
        ('wasi', '*'),
    ]
    search_paths = (
        _PACKAGES_PATH / 'lower_layer',
    )

    composition = compose(dependencies, search_paths)

    wasi_entries = {
        k: v for k, v in composition.items() if v[2] == 'wasi'
    }
    assert len(wasi_entries) == 1, \
        f'Expected 1 wasi entries, got {wasi_entries}'
    # We are testing here that Version saves the the dep with the name
    # we expect
    assert 'wasi::0.11.1+wasi.snapshot.preview1' in composition


def test_vendored_registry_is_scoped_to_its_own_subtree():
    # pkg-v ships its dependencies vendored beside it, flattened the way
    # 'cargo vendor' produces them: vend-a is a direct dependency, vend-b is
    # a dependency of vend-a, and both sit at the top of pkg-v's vendor dir.
    dependencies = [
        ('pkg-v', '*'),
    ]
    search_paths = (
        _PACKAGES_PATH / 'vendoring_layer',
    )

    composition = compose(dependencies, search_paths)

    # the vendored crates are reachable, including the one which is only
    # needed transitively and whose own parent vendored nothing
    assert set(composition) == {
        'pkg-v::1.0.0', 'vend-a::1.0.0', 'vend-b::1.0.0'}, f'{composition}'

    # and they resolve out of pkg-v's vendor directory, not the search path
    _, location, _ = composition['vend-b::1.0.0']
    assert location.parent.name == 'vendor', f'{location}'


def test_vendored_registry_is_not_visible_to_other_packages():
    # pkg-e comes from a different search path and vendors nothing, so the
    # crates pkg-v vendored must not be candidates for it
    dependencies = [
        ('pkg-e', '*'),
        ('vend-a', '*'),
    ]
    search_paths = (
        _PACKAGES_PATH / 'upper_layer',
        _PACKAGES_PATH / 'lower_layer',
        _PACKAGES_PATH / 'vendoring_layer',
    )

    composition = compose(dependencies, search_paths)

    assert 'vend-a::1.0.0' not in composition, f'{composition}'
