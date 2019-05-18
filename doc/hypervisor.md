Preparing the Hypervisor
========================

In production OpenStack environments there's no single hypervisor, but rather there are many
controllers running on dedicated hardware with redundancy. For our lab we will converge all these
roles in a single machine. However, it's important to understand that this machine will be
fulfilling several roles.

Our Hypervisor will need two NICs, with one NIC on our work LAN and one NIC on a dedicated OpenStack
control plane LAN.

/diagram/


Step 1: Install the operating system
------------------------------------

Start with installing [CentOS](https://www.centos.org/). Tested with version 7.6. The minimal
install (with no desktop environment) is good enough. We will need:

* The root user password
* Its IP address on the work LAN 

Our scripts will be making changes to this machine. We will do our best to isolate our work: most of
it will be under the user "stack", and most of what we run will be inside virtual machines, which we
will set up with libvirt for the "stack" user session.

However, some work will have to be done in root: installing some user packages and setting up
custom network bridges.


Step 2: Prepare the Hypervisor
------------------------------

Edit `configuration/environment` and set `HYPERVISOR_ADDRESS` to point to our Hypervisor. We can
use a host name. Then run:

    hypervisor/prepare

We will be prompted only once for the root password for the Hypervisor, which we will use to
authorize a keypair for ssh.

What this script does:

* Installs [libvirt](https://libvirt.org/) and related tools, such as
  [VirtualBMC](https://docs.openstack.org/virtualbmc/latest/), which provides an
  [IPMI](https://en.wikipedia.org/wiki/Intelligent_Platform_Management_Interface) for libvirt
  virtual machines
* Sets up network bridges to be used by our libvirt virtual machines, configured by
  `configuration/libvirt/networks/virtual-machine-control-plane.xml` and
  `configuration/libvirt/networks/openstack-control-plane.xml`
* Creates and configures the "stack" user

Note that all OpenStack packages and container images, including those for TripleO, are provided
by the [DLRN (pronounced "Delorean") project](https://dlrn.readthedocs.io/en/latest/).

After it's done we will find some files under our `workspace/` directory:

* `workspace/keys/root@hypervisor`
* `workspace/keys/root@hypervisor.pub`
* `workspace/keys/stack@hypervisor`
* `workspace/keys/stack@hypervisor.pub`
* `workspace/passwords/stack@hypervisor`
* `workspace/ssh.config` is updated for `hypervisor-root` and `hypervisor-stack`

Our scripts will later on add more keys and passwords and keep `workspace/ssh.config` updated.
That last file is especially useful: it configures custom hosts that we can use it to ssh from our
orchestrator to our lab machines, including virtual machines running inside the Hypervisor (via ssh
proxying).

Use the `hypervisor/ssh` and `hypervisor/rsync` shortcuts to use this config. Examples:

    hypervisor/ssh hypervisor-stack
    hypervisor/ssh hypervisor-root "ls -al"
    hypervisor/rsync myfile.txt hypervisor-stack:/text/

Now that we have libvirt installed we can also use its CLI,
[virsh](https://libvirt.org/virshcmdref.html), via our shortcut: 

    hypervisor/virsh list

By default this shortcut will use the "stack" user session. Because we haven't created any virtual
machines yet, the above should result in an empty table. Use `-r` as the first argument to connect
to to libvirt's system session (as user root):

    hypervisor/virsh -r net-list

You should see the two networks we created in this step. 

(Note that if we have libvirt installed on our orchestrator it would also be possible to connect
[remotely](https://libvirt.org/remote.html) to the Hypervisor's instance via a "qemu+shh:" or
similar URI.) 


Step 3: Prepare TripleO
-----------------------

Now that our Hypervisor is set up for hosting virtual machines we will prepare a virtual machine
for installation of our OpenStack infrastructure manager,
[TripleO](https://docs.openstack.org/tripleo-docs/latest/):

    hypervisor/tripleo/prepare

What this script does:

* Creates a virtual machine named `tripleo` based on a CentOS image using
  [cloud-init](https://cloudinit.readthedocs.io/en/latest/) to initialize it and configured by 
  `configuration/libvirt/virt-install/tripleo.ini` and
  `configuration/libvirt/cloud-init/tripleo.yaml`
* Installs TripleO client on it, which we will use in the next step to install TripleO
  (yes, it's complex enough that it deserves its own step!)
* Installs Ceph Ansible playbooks on it, which TripleO will use later to install Ceph on cloud
  nodes 
* Creates and configures the "stack" user, which will be used by TripleO client to configure TripleO
  (though note that it does have sudo access, which will be necessary for *installing* TripleO)    
  
After it's done we will find some more files under our `workspace/` directory:

* `workspace/keys/stack@tripleo`
* `workspace/keys/stack@tripleo.pub`
* `workspace/ssh.config` is updated for `tripleo-stack`

We can now connect to the `tripleo` virtual machine:

    hypervisor/ssh tripleo-stack

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


Step 4: Install TripleO
-----------------------

Now that we have the `tripleo` virtual machine ready with the TripleO client we can use it to
install TripleO: 

    hypervisor/tripleo/install

This step is almost entirely handled by the `openstack undercloud install` command. It is configured
by `configuration/tripleo/undercloud.conf`. Internally it has several steps and takes a while to
complete, ~ 15 minutes.

Internally it will be using [Puppet](https://puppet.com/) to orchestrate the installation and
orchestration of the various OpenStack undercloud services as containers to be run by
[Podman](https://podman.io/). Containers allow for better isolation and portability.

After it's done we can access the undercloud's `openstack` command via a shortcut:

    hypervisor/tripleo/openstack

We can also access the individual service containers via the `hypervisor/tripleo/podman`,
`hypervisor/tripleo/podman-bash`, and `hypervisor/tripleo/podman-restart` shortcuts. Run any of
those shortcuts without any argument to get a list of available containers. For example, to get
a shell into the `ironic_conductor` container and see the logs:

    hypervisor/tripleo/podman-bash ironic_conductor
    cat /var/log/ironic/ironic-conductor.log

Note that configuration files for the containers are exported from the virtual machine, in the
`/var/lib/config-data/puppet-generated/` directory. For example, to edit `ironic.conf`:

    hypervisor/ssh tripleo-stack
    vi /var/lib/config-data/puppet-generated/ironic/etc/ironic/ironic.conf

To use the file we will need to restart the container:

    hypervisor/tripleo/podman-restart ironic_conductor


How to Reset
------------

You can start from scratch if you experience any failures in the above or later steps. This script
will delete all the virtual resources from the Hypervisor:

    hypervisor/clean

You may need to run it several times until it completes successfully because some resources might
be in an indeterminate state when you run it.

You can also combine `clean` and `prepare`:

    hypervisor/prepare -c
