Chapter 1: Preparing the Orchestrator
=====================================

The Orchestrator machine is where we will be running the scripts in this repository.

The requirement is a minimal Unix-like environment. Specifically we will need bash, ssh, sshpass,
rsync, sed, grep, and awk. We will be doing no changes to this machine so it's perfectly fine to use
an existing workstation.

Any Linux or BSD would be good, including macOS and the
[Windows Subsystem for Linux (WSL)](https://docs.microsoft.com/en-us/windows/wsl/about).
Most of these environments will already have everything we need out of the box, except perhaps for
sshpass. To install it on Fedora:

    sudo dnf install sshpass

Alternatively, we *can* run orchestration on the Manager machine itself, in which case the two
machine roles would be combined into one physical machine and the Manager address would be
`localhost`.


Next
----

[Continue to Chapter 2: Prepare the Manager](manager.md)
