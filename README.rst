pallet-patcher
==============

|build| |coverage| |pypi|

*Tools for working with curated collections of Cargo packages*

``pallet-patcher`` is a command-line tool designed to compose a collection of locally available Cargo packages that satisfy the dependencies of a given Cargo manifest. It resolves dependencies from provided local search paths, identifying compatible crate versions, and outputs patch arguments or configuration that can be supplied directly to Cargo. This is particularly useful for building Cargo projects in offline environments or working with specific layers of dependencies.

Motivation
----------

Cargo is designed to be highly reliable by ensuring that dependencies are either pulled from a central registry (like crates.io) or explicitly defined by their location (e.g., ``path = "../my-crate"``). While this approach provides great predictability, there are specialized use cases where developers may need more flexibility—specifically, when resolving dependencies from dynamically provided local directories without modifying the original source code.

Other build systems and environments often provide mechanisms to search for dependencies across multiple locations:

- **CMake** utilizes ``CMAKE_PREFIX_PATH`` for package discovery.
- **pkg-config** leverages ``PKG_CONFIG_PATH`` to locate libraries.
- **Python** uses ``PYTHONPATH`` to find modules.

``pallet-patcher`` provides a similar workflow for the Cargo ecosystem. It is particularly useful for complex development environments where projects are composed from multiple independent local layers or for building in restricted, offline environments where dependency sources are managed externally.

By scanning a list of search paths and resolving compatible crate versions using standard SemVer rules, ``pallet-patcher`` dynamically generates the necessary Cargo configuration to patch dependencies with their discovered local counterparts. This provides a bridge between Cargo's strict dependency management and the need for dynamic, path-based discovery in specific workflows.

Usage
-----

.. code-block:: text

    usage: pallet-patcher [-h] [--output-format {args,toml}]
                          manifest_path search_path [search_path ...]

    positional arguments:
      manifest_path         Path to the Cargo.toml file on disk
      search_path           List of local registry sources to search for packages

    options:
      -h, --help            show this help message and exit
      --output-format {args,toml}
                            Choose the output format for Cargo configuration. 'args' (default)
                            for CLI arguments, or 'toml' for configuration file contents.

Example
-------

Generate Cargo command-line arguments to patch dependencies using locally available crates:

.. code-block:: bash

    pallet-patcher Cargo.toml /usr/share/cargo/registry ../another/path

Output:

.. code-block:: text

    --config=patch.'crates-io'.'pkg::0.1.0'.package='pkg'
    --config=patch.'crates-io'.'pkg::0.1.0'.path='/path/to/local/crates/pkg'

Generate a TOML configuration for your ``.cargo/config.toml``:

.. code-block:: bash

    pallet-patcher --output-format toml Cargo.toml /usr/share/cargo/registry > .cargo/config.toml

Output:

.. code-block:: toml

    [patch.'crates-io'.'pkg::0.1.0']
    package = 'pkg'
    path = '/usr/share/cargo/registry/pkg'

.. |build| image:: https://img.shields.io/github/actions/workflow/status/ros-infrastructure/pallet-patcher/ci.yaml?branch=main&event=push
   :target: https://github.com/ros-infrastructure/pallet-patcher/actions/workflows/ci.yaml?query=branch%3Amain+event%3Apush
.. |coverage| image:: https://img.shields.io/codecov/c/github/ros-infrastructure/pallet-patcher/main
   :target: https://app.codecov.io/gh/ros-infrastructure/pallet-patcher/branch/main
.. |pypi| image:: https://img.shields.io/pypi/v/pallet-patcher
   :target: https://pypi.org/project/pallet-patcher/
