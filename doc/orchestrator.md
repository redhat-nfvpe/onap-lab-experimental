Preparing the Orchestrator
==========================

The Orchestrator machine is where you will be running the scripts in this repository. It must have
Linux and Python 2.7.

It may be convenient for it to have CentOS, for consistency with the rest of the lab, but that is
not a requirement, as any popular Linux should be fine. We will be doing no major changes to this
machine, so you may decide to use an existing bare metal workstation. Alternatively, a virtual
machine can be used instead for better isolation and portability.
[Vagrant](https://www.vagrantup.com/) is a convenient tool for quickly getting such a virtual
machine up and running.

TODO Vagrant instructions

As yet another alternative, you *can* run orchestration on the Hypervisor machine itself, in which
case the two machine roles would be combined into one physical machine.


Install InfraRed
----------------

We'll start by installing [InfraRed](https://infrared.readthedocs.io/), which is an enhanced
[Ansible](https://www.ansible.com/) orchestration environment. InfraRed comes with powerful plugins
to handle all our RDO installation tasks.

We'll be installing it in a Python virtual environment and pinning it to a specific version in order
to ensure compatibility with this guide. Just run this:

    ./install-infrared

By default we're putting the virtual environment in `~/infrared-virtualenv/` directory and using
`~/infrared-home/` for its home. Note the hidden directories and files therein. You can change these
defaults by editing `conf/env`.

While running InfraRed, logs and task variables will be output to the `work/` directory here.

The rest of the orchestrator scripts used in this guide will be using this InfraRed installation
automatically. In case you want to manually activate the InfraRed virtual environment and checkout
the workspace:

    . ~/infrared-virtualenv/bin/activate
    export IR_HOME=~/infrared-home
    infrared workspace checkout onap-lab


How to Reset
------------

This will remove all directories created above, which includes your InfraRed workspace:

    ./remove-infrared
