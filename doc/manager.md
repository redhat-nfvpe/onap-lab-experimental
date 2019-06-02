Chapter 2: Prepare the Manager
==============================

In production OpenStack environments there's no single controller, instead there would be many
controllers of various kinds running on dedicated hardware with redundancy. For our lab we will
converge all these roles in a single machine. However, it's important to understand that this
machine will be fulfilling several roles. In order to keep these roles isolated we will be running
each role in a virtual machine, which will also make it much easier to tear down and rebuild roles. 

Our Manager will need two NICs, with one NIC on our work LAN and one NIC on a dedicated OpenStack
control plane LAN.

/diagram/


Step 1: Install the operating system
------------------------------------

Start with installing [CentOS](https://www.centos.org/). Tested with version 7.6. The minimal
install (with no desktop environment) is good enough. We will need:

* The root user password
* Its IP address on the work LAN 

Our scripts in the next steps will be making changes to this machine. They do the best they can to
isolate our work: most of it will be under the user "manager", and most of what they run will be
inside virtual machines, which we will set up with libvirt.

However, some work will have to be done in root: installing some utility packages and setting up
custom network bridges as well as the virtual machines themselves.


Step 2: Prepare the Manager
------------------------------

Edit `configuration/environment` and set `MANAGER_IP_ADDRESS` to point to our Manager. We can use
a host name. Then run:

    manager/prepare

We will be prompted only once for the root password for the Manager, which we will use to
authorize a keypair for ssh.

What this script does:

* Installs [libvirt](https://libvirt.org/) and related tools, such as
  [VirtualBMC](https://docs.openstack.org/virtualbmc/latest/), which provides an
  [IPMI](https://en.wikipedia.org/wiki/Intelligent_Platform_Management_Interface) for libvirt
  virtual machines
* Sets up network bridges to be used by our libvirt virtual machines, configured by
  `configuration/libvirt/networks/virtual-machine-control-plane.xml` and
  `configuration/libvirt/networks/openstack-control-plane.xml`
* Creates and configures the "manager" user

After it's done we will find some files under our `workspace/` directory:

* `workspace/keys/root@manager` and `workspace/keys/root@manager.pub`
* `workspace/keys/manager@manager` and `workspace/keys/manager@manager.pub`
* `workspace/passwords/manager@manager`
* `workspace/ssh.config` is updated for `manager-root` and `manager`

Our scripts will later on add more keys and passwords and keep `workspace/ssh.config` updated.
That `ssh.config` file is especially useful: it configures custom hosts that we can use it to ssh
from our orchestrator to our lab machines, including virtual machines running inside the Manager
and OpenStack infrastructure nodes. The `./ssh` and `./rsync` shortcuts use this config. Examples:

    ./ssh manager
    ./ssh manager-root "ls -al"
    ./rsync myfile.txt manager:/text/

Now that we have libvirt installed we can also use its CLI,
[virsh](https://libvirt.org/virshcmdref.html), via our shortcut: 

    manager/virsh list

Because we haven't created any virtual machines yet, the above should result in an empty table. But
this will show results:

    manager/virsh net-list

You should see the two networks we created in this step. 

(Note that if we have libvirt installed on our orchestrator it would also be possible to connect
[remotely](https://libvirt.org/remote.html) to the Manager's instance via a "qemu+ssh:" or
similar URI.)


Step 3: Prepare TripleO
-----------------------

Now that our Manager is set up for hosting virtual machines we will prepare a virtual machine
for installation of our OpenStack infrastructure manager,
[TripleO](https://docs.openstack.org/tripleo-docs/latest/):

    manager/tripleo/prepare

What this script does:

* Creates a virtual machine named `tripleo` based on a CentOS image using
  [cloud-init](https://cloudinit.readthedocs.io/en/latest/) to initialize it and configured by 
  `configuration/libvirt/domains/tripleo/virt-install.ini` and
  `configuration/libvirt/domains/tripleo/cloud-config.yaml`
* Installs TripleO-client on it, which we will use in the next step to install TripleO (yes, it's
  complex enough that it deserves its own step)
* Installs Ceph Ansible playbooks on it, which TripleO will use later to install Ceph on cloud
  nodes 
* Creates and configures the "stack" user, which will be used by TripleO client to configure TripleO
  (though note that it does have sudo access, which will be necessary for *installing* TripleO)    

Note that OpenStack packages, including those for TripleO and TripleO-client, are provided by the
[DLRN (pronounced "Delorean") project](https://dlrn.readthedocs.io/en/latest/). We will be
installing more than 500 packages in this step!
  
After it's done we will find some more files under our `workspace/` directory:

* `workspace/keys/stack@tripleo` and `workspace/keys/stack@tripleo.pub` are they keypair for the
  virtual machine
* `workspace/passwords/stack@tripleo` is the password
* `workspace/ssh.config` is updated for `tripleo`

Logs and configuration files have been fetched to the `workspace/results/` directory. Some useful
ones are from:

* Manager: `/var/log/libvirt/qemu/tripleo.log`

In the Manager's `manager` user's home directory:

* `/home/manager/keys/stack@tripleo` and `/home/manager/stack@tripleo.pub`
* `/home/manager/libvirt/images/tripleo.qcow2` is our virtual machine drive image

We'll wait a few seconds for the `tripleo` virtual machine to start up and then we can connect to
it:

    ./ssh tripleo

Note that if you reboot the Manager this virtual machine will also be rebooted.

> You might be wondering why our OpenStack infrastructure manager is called "TripleO". It's actually
named after the pronunciation of "OoO" which is an acronym for "OpenStack on OpenStack". Wait, what?

> The idea is this: our infrastructure, which comprises various computers and storage devices and
network cards and switches, is itself a bit like a "cloud", though instead of being comprised of
virtual machines and virtual storage and virtual networks, which is what we mostly associate with
"cloud", it is (mostly) physical.

> And OpenStack does support physical resources. This functionality is provides by OpenStack
component called [Ironic](https://wiki.openstack.org/wiki/Ironic), which is used to manage physical
machines, or "bare metal". In a typical OpenStack cloud it handles the provisioning of bare metal
resources in addition to the more typical virtual resources.

> You might already guess where this is going: in TripleO we will be using OpenStack itself, relying
heavily on Ironic, to manage our infrastructure as bare metal resources. The advantage is that we
can then use all the usual OpenStack tools to manage our infrastructure. This allows us to use the
same paradigm to manage the infrastructure as we use to manage our cloud workloads.

> The result is a deployment with *two* separate clouds: our infrastructure is called the
"undercloud", and our "actual" cloud, installed on the infrastructure, is called the "overcloud".
They could potentially be running different versions of OpenStack!  

> TripleO does not require a full-blown OpenStack installation. For our lab we will be using a
minimal all-in-one installation within our `tripleo` virtual machine. But in production we can
indeed divide the undercloud OpenStack services between many machines, with full redundancy, high
availability, and scalability -- all the things that OpenStack already provides.

> Confused? You really don't have to worry about it too much. The fact that our infrastructure
manager is itself implemented in OpenStack is just that: an implementation detail.

> Note that in Red Hat OpenStack Platform (RHOSP) TripleO is called "Director".


Step 4: Deploy TripleO
----------------------

Now that we have the `tripleo` virtual machine ready with the TripleO client we can use it to
deploy TripleO:

    manager/tripleo/install

This step is almost entirely handled by the `openstack undercloud install` command. It is configured
by `configuration/tripleo/undercloud.conf`. Internally it has several steps and takes a while to
complete, ~ 15 minutes.

Internally it will be using [Puppet](https://puppet.com/) to orchestrate the installation and
configuration of the various OpenStack undercloud services as containers to be run by
[Podman](https://podman.io/). Containers allow for better isolation and portability. The undercloud
itself is installed using the OpenStack [Heat](https://docs.openstack.org/heat/latest/)
orchestration and [Mistral](https://docs.openstack.org/mistral/latest/) workflow services, which
internally uses [Ansible](https://www.ansible.com/). The OpenStack container images are provided by
the [Kolla project](https://docs.openstack.org/kolla/latest/).

Logs and configuration files have been fetched to the `workspace/results/` directory. Some useful
ones are from:

* TripleO: `/var/log/containers/mistral/engine.log`
* TripleO: `/var/log/containers/heat/heat-engine.log`

In TripleO's `stack` user's home directory:

* `/home/stack/install-undercloud.log` is a copy of the output we saw during this step
* `/home/stack/undercloud.conf` is based on our `configuration/tripleo/undercloud.conf`
* `/home/stack/tripleo-config-generated-env-files/undercloud_parameters.yaml` incorporates
   the above two files
* `/home/stack/undercloud-passwords.conf`
* `/home/stack/tripleo-undercloud-passwords.yaml` incorporates the above file and also ssh keys
* `/home/stack/stackrc` sets up a shell environment for accessing the undercloud

We can now access the undercloud's `openstack` command via a shortcut (that uses the `stackrc`
mentioned above), e.g.:

    manager/tripleo/openstack network list

The `openstack` command is mostly documented
[here](https://docs.openstack.org/python-openstackclient/stein/cli/), though note that it is
extensible. Ironic adds
[these commands](https://docs.openstack.org/python-ironicclient/latest/cli/osc_plugin_cli.html)
and TripleO adds commands to deploy itself (`undercloud install`) and OpenStack
(`overcloud deploy`, see the next chapter).

We can directly access the individual service containers on any machine via the `./podman`,
`./podman-bash`, and `./podman-restart` shortcuts. Run any of them without arguments to get a list
of available service containers. For example, to get a shell into the `mistral_engine` service
container:

    ./podman-bash tripleo mistral_engine
    cat /var/log/mistral/engine.log

(Note that `podman-bash` does not ssh into the container, but rather explicitly executes bash within
the container. These are lightweight containers that are not running ssh servers.)

Podman's CLI intentionally mimics Docker's, so if you're familiar with commands like `docker ps`
just replace the command with `podman`: `./podman tripleo ps`.

We don't actually have to access the containers to get to the logs, because the log directories
are shared from the host virtual machine at `/var/log/containers/`, for example the log we saw
above is also here:

    ./ssh tripleo
    cat /var/log/containers/mistral/engine.log

Unlike logs, which are shared from the host, configuration files for the containers are *imported*
from the host when they start up, from its `/var/lib/config-data/puppet-generated/` directory. So,
to manually edit `ironic.conf`:

    ./ssh tripleo
    vi /var/lib/config-data/puppet-generated/ironic/etc/ironic/ironic.conf

To use the file we will need to restart the service container:

    ./podman-restart ironic_conductor


How to Reset
------------

You can start from scratch if you experience any failures in the above or later steps. This script
will delete all the virtual resources from the Manager:

    manager/clean

You may need to run it several times until it completes successfully because some resources might
be in an indeterminate state when you run it.

You can also combine `clean` and `prepare`:

    manager/prepare -c


Next
----

[Continue to Chapter 3: Install OpenStack](openstack.md)
