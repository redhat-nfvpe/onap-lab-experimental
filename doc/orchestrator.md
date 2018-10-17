Preparing the Orchestrator
==========================

We'll start by installing [InfraRed](https://infrared.readthedocs.io/), which is an enhanced
[Ansible](https://www.ansible.com/) orchestration environment. InfraRed comes with plugins to handle
all our RDO installation tasks.

We'll be installing it in Python virtual environment and pinning it to a specific version in order
to ensure compatibility with this guide. Just run this:

    ./install-infrared

By default we're putting the virtual environment in `~/infrared` directory. To activate it and
checkout our workspace:

    . ~/infrared/bin/activate
    infrared workspace checkout onap-lab

Ansible will access the Hypervisor over ssh as the root user. This means that you must have a
private key for which the paired public key is registered with root@Hypervisor. Note that this
is true even if the Orchestrator and Hypervisor are the same physical machine, in which case Ansible
will be ssh-ing to localhost. To create and copy the key:

	./create-keypair
	ssh-copy-id root@hypervisor_address
