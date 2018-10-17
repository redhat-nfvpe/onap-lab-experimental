Preparing the Hypervisor
========================

The installation process makes certain assumptions about the Hypervisor operating system. Be aware
of some potential conflicts:

* Do _not_ create a user called `stack`.
* Do _not_ install the `python-virtualenv` operating system package. Infrared will be installing it
  via `pip`, and the two installation methods could conflict.


Step 1: Provision the virtual resources
---------------------------------------

Although technically we can install the cloud manager software directly on the Hypervisor's
operating system, we will instead install it in a virtual machine. This separation allows for better
control and more flexible administration. So, our first step is to provision that virtual machine.

However, before we do that, note that in an all-in-one setup we _also_ want to create virtual
machines to replace the cloud physical machines. So, for efficiency, we will also provision them in
this step.

This step is handled by Infrared/Ansible on the Orchestrator:

    ./provision-virtual-resources

It should take just a few minutes.

When finished, you can login to the Hypervisor and notice a few changes in addition to the new
virtual machines:

* Many new virtual network interfaces
* `/etc/hosts` has domain names for the virtual machines
* Virtual storage is in the default location: `/var/lib/libvirt/images/`
* A new `stack` user

Also, root user now has a keypair (at `/root/.ssh`) that can be used to login, also as root, to the
cloud manager virtual machine. So, to login into it we must use `sudo`:

	sudo ssh undercloud-0

Currently it's a fresh CentOS virtual machine. The next step will install our cloud manager software
in it.

The virtual machines run on KVM and can be managed by libvirt and the
[virsh](https://libvirt.org/virshcmdref.html) tool. Note that because they were created under the
root user, you must use `sudo` to access them, e.g.:

    sudo virsh list 

You can also use a virsh client on a remote machine (such as the Orchestrator), e.g.:

    virsh --connect=qemu+ssh://root@hypervisor_address/system list


Step 2: Install the cloud manager
---------------------------------

> You might be wondering why the cloud manager virtual machine is called "undercloud". To understand
this term, first you must understand that the cloud manager software is _itself_ implemented as an
all-in-one OpenStack cloud.

> Why use OpenStack? First, consider why a cloud manager is even necessary. After all, you could
potentially create an OpenStack cloud manually: take a bunch of physical machines, install the
necessary OpenStack components on them, and configure them to work together. But in real life we
need something more automated. We need to easily add and remove physical machines to and from the
cloud, and also need to install and configure the OpenStack components on them.

> Well--guess what?--that's exactly the kind of work that OpenStack itself was designed to do,
though with a small twist: we usually think of a cloud as comprising virtual machines, but actually
OpenStack can also manage physical machines via its [Ironic](https://wiki.openstack.org/wiki/Ironic)
component, which relies on PXE and IPMI technologies to bootstrap the bare metal. Once they're
provisioned, there is no significant difference between managing virtual machines and managing
physical machines.

> This, then, is what our cloud manager does: allows us to add and remove machines to and from the
cloud. Together, all these machines comprise the "undercloud". The "overcloud" comprises our actual
cloud resources provisioned on top of these machines. In effect, what we have here is one OpenStack
cloud running on top another: OpenStack-On-OpenStack, or
[TripleO](https://wiki.openstack.org/wiki/TripleO).

> (Actually, adding new machines to the cloud is not just about installing and configuring them, but
may also require configuring the network. At the bare minimum this could mean allocating a secure
IP address for the machine but it may involve more complex SDN work. For example, a single cloud may
comprise several separate LANs and indeed be distributed across several data centers. Again, this
is something that OpenStack can already handle for the actual cloud, so it can do the same for our
undercloud.)

> Confused? You really don't have to worry about it too much. The fact that our cloud manager is
itself implemented in OpenStack is precisely just an implementation detail. Indeed, the undercloud
and overcloud could each be running on entirely different versions of OpenStack. All you need to
know is that the virtual machine called "undercloud" is your cloud manager.

OK! So, now let's install our cloud manager ("undercloud"):

    ./install-undercloud

This can take up to 30 minutes.

You can connect to the undercloud just like any other OpenStack. Full access details are in the
`stackrc` file in the `undercloud-0` machine. For example, let's see what hosts are running in it
(run on Hypervisor):

	sudo ssh undercloud-0
	. stackrc
	openstack host list

(In case you're wondering: yes, these are virtual machines running inside a virtual machines. This
setup relies on nested virtualization functionality.)

On `undercloud-0` you'll also find useful logs and access files:

	/home/stack/undercloud_install.log
	/home/stack/undercloud-passwords.conf
	/home/stack/undercloud.conf


Reset
-----

If you experienced any failures in the above or later steps, you can start from scratch. Try runnin
this at the Orchestrator:

    ./delete-virtual-resources

However, if the virtual machines are in a broken state, some resources might not be deleted by this.
You can makre sure to completely remove _all_ virtual resources by running this script at the
Hypervisor:

	sudo ./reset-virtual-resources