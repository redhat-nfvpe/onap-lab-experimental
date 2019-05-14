hypervisor/undercloud/podman container list

Preparing the Hypervisor
========================

In production OpenStack environments there's no single hypervisor, but rather there are many
controllers running on dedicated hardware, with redundancy. For our lab we will converge all these
roles in a single machine. However, it's important to understand that this machine will be
fulfilling several roles.


Step 1: Install the operating system
------------------------------------

Start with installing [CentOS](https://www.centos.org/). Tested with version 7.6. The minimal
install is good enough.

The Hypervisor installation process makes certain assumptions about the machine, so be aware of some
potential conflicts:

* Do _not_ create a user called `stack`.
* Do _not_ install the `python-virtualenv` operating system package. InfraRed will be installing it
  via `pip` and the two installation methods could conflict.

Edit `conf/env` and set `HYPERVISOR_ADDRESS` to point to your Hypervisor. You can use a host name.

Ansible on the Orchestrator will be accessing the Hypervisor over ssh as the root user using key
authentication. This means that you must have a private key for which the paired public key is
registered with root on the Hypervisor.

(Note that this is true even if the Orchestrator and Hypervisor are the same physical machine, in
which case Ansible will be ssh-ing to `localhost`.)

We provide a script that makes sure you have a key pair on the Orchestrator and copies the public
key to the Hypervisor:

    ./install-orchestrator-keypair

You can then ssh with script:

	./ssh-hypervisor


Step 2: Provision the virtual resources
---------------------------------------

Because our Hypervisor will be running several controllers once, we will have the software for each
controller in its own virtual machine. This separation allows for more isolation and easier
administration, and also mimics production environments in which controllers would be running on
dedicated hardware.

There's actually yet another level of isolation: within some controller virtual machines we will be
running individual services as [Docker](https://www.docker.com/) containers. Internally,
[Puppet](https://puppet.com/) is used to deploy these services.

In this step we will provision all virtual resources at once. On the Orchestrator:

    ./provision-hypervisor-virtual

It should take just a few minutes. Internally, [virsh](https://libvirt.org/virshcmdref.html) is
used to provision the virtual resources on top of [libvirt](https://libvirt.org/).

When finished, you can check out the virtual machines using virsh. We provide a `./virsh-hypervisor`
as a shortcut to connect remotely. Example: 

    ./virsh-hypervisor list

If you `./ssh-hypervisor` you'll notice:

* Many new virtual network interfaces (`ip addr`)
* Virtual storage is located in `/home/libvirt/`


Step 3: Install the infrastructure controller ("undercloud")
------------------------------------------------------------

On the Orchestrator:

    ./install-undercloud

This can take about 20 minutes.

If you `./ssh-hypervisor` you'll notice:

* A new `stack` user
* `/etc/hosts` has domain names for the virtual machines (though only `undercloud-0` has an IP
  address)
* The root user now has a keypair (at `/root/.ssh`) that can be used to ssh, either as user `stack`
  *or* as `root`, to the `undercloud-0` virtual machine (note that user `stack` has sudo access)

The `./ssh-controller` can be used to double-ssh from the Orchestrator to the controller virtual
machines:

    ./ssh-controller undercloud-0

If you `./ssh-controller undercloud-0` you'll find useful logs and access files for this
step:

    /home/stack/undercloud_install.log
    /home/stack/undercloud-passwords.conf
    /var/log/containers/
    /home/stack/undercloud.conf
    /home/stack/stackrc

> You might be wondering why the infrastructure controller virtual machine is called "undercloud".
To understand this term, first you must understand that the infrastructure controller software is
_itself_ implemented as a small all-in-one OpenStack cloud.

> Why use OpenStack to manage OpenStack? First, consider why an infrastructure controller is even
necessary. After all, you could potentially create an OpenStack cloud manually: take a bunch of
physical machines, install the necessary OpenStack components on them, and configure them to work
together. But for a real cloud we need some automation. We need to easily add and remove physical
machines to and from the cloud, and also need to install and configure the OpenStack components on
them.

> Well--guess what?--that's exactly the kind of work that OpenStack itself was designed to do,
though with a small twist: we usually think of a cloud as comprising virtual machines, but actually
OpenStack can also manage physical machines via its [Ironic](https://wiki.openstack.org/wiki/Ironic)
component, which relies on PXE and IPMI technologies to bootstrap the bare metal. Once they're
provisioned, there is no significant difference between managing virtual machines and managing
physical machines.

> This, then, is what our infrastructure controller does: allows us to add and remove machines to
and from the cloud. Together, all these machines comprise the "undercloud". The "overcloud"
comprises our actual cloud resources provisioned on top of these machines. In effect, what we have
here is one OpenStack cloud running on top another: OpenStack-On-OpenStack, a.k.a.
[TripleO](https://docs.openstack.org/tripleo-docs/latest/).

> (Actually, adding new machines to the cloud is not just about installing and configuring them but
may also require configuring the network. At the bare minimum this could mean allocating a secure
IP address for the machine but it may involve more complex SDN work. For example, a single cloud may
comprise several separate LANs and indeed be distributed across several data centers. Again, this
is something that OpenStack can already handle for the "actual" cloud, so it can do the same for our
undercloud.)

> Confused? You really don't have to worry about it too much. The fact that our infrastructure
manager is itself implemented in OpenStack is just that: an implementation detail. Indeed, the
undercloud and overcloud could each be running on entirely different versions of OpenStack. All you
need to know is that the virtual machine called "undercloud-0" is your infrastructure controller.

You can connect to the undercloud just like to any other OpenStack deployment. However, note that
its virtual machine, `undercloud-0`, is not network-accessible outside of the Hypervisor. We provide
`./openstack-undercloud` as a shortcut to access it from the Orchestrator. For example, let's see
what networks we have:

    ./openstack-undercloud network list

Note that at this stage `./openstack-undercloud server list` will be empty because have not yet
on-boarded any infrastructure.

Also note that in TripleO version 13 ("queens") all OpenStack services run as simple executables,
rather than Docker containers. The other controllers for "queens" all use Docker containers (see
step 4, below). From version 14 ("rocky") TripleO also uses containers. 


Step 4: Install infrastructure images
-------------------------------------

Our infrastructure controller ("undercloud") will be providing operating system images, based on
CentOS, for bootstrapping the other controllers. On the Orchestrator:

    ./install-overcloud-images

It should take just a few minutes.

By default the ready-made images will be downloaded for you. It's also possible to build these
images locally, which would take about 15 minutes:

    ./install-overcloud-images -b

To list the installed images:

    ./openstack-undercloud image list

If you `./ssh-controller undercloud-0` you'll find useful logs for this step:

    /home/stack/overcloud-full.log
    /home/stack/openstack-build-images.log
    /home/stack/ironic-python-agent.log


Step 5: Install other cloud controllers
---------------------------------------

Now that we have an infrastructure controller ("undercloud") we can use it provision and install our
other controllers ("overcloud"). Internally this is done using Ansible,
[Heat](https://docs.openstack.org/heat/latest/), and
[Mistral](https://docs.openstack.org/mistral/latest/) on the undercloud.
[Kolla](https://docs.openstack.org/kolla/latest/) is used as the source of the Docker container
images.

Our overcloud installation consists of these controllers:

* `controller-0`: Manages networking ([Neutron](https://docs.openstack.org/neutron/latest/)) as well
  as virtual machine scheduling
  ([nova-scheduler](https://docs.openstack.org/nova/latest/cli/nova-scheduler.html)).
* `ceph-0`: [Ceph](https://ceph.com/) is a powerful distributed storage system with good OpenStack
  and OKD integration. Ceph will provide our
  block storage ([Cinder](https://docs.openstack.org/cinder/latest/)),
  file storage ([Manila](https://docs.openstack.org/manila/latest/)),
  and object storage ([Swift](https://docs.openstack.org/swift/latest/)).
  (Actually, some Ceph services will also be running on `controller-0`.)

On the Orchestrator:

    ./install-overcloud

This can take ??? minutes.

If you `./ssh-controller undercloud-0` you'll find useful logs and topology files for this step:

    /home/stack/overcloud_install.log
    /home/stack/overcloud_deployment_*.log
    /home/stack/openstack_failures_long.log
    /var/lib/mistral/overcloud/ansible.log
    /home/stack/instackenv.json
    /home/stack/containers-prepare-parameter.yaml

The root user at the Hypervisor (and also in `undercloud-0`) now has a keypair (at `/root/.ssh`)
that can be used to login as user `heat-admin` to the controller virtual machines. To login, you
need to find their addresses, which you can see with the `openstack server info` command. The
`./ssh-controller` will do this for you and double-ssh from the Orchestrator:

    ./ssh-controller controller-0

Once in a controller you can see its running service as containers:

    sudo docker container list


Step 6: Configure cloud controllers
-----------------------------------

On the Orchestrator:

    ./configure-overcloud

This can take ??? minutes.



How to Reset
------------

If you experience any failures in the above or later steps then you can start from scratch. This
script will delete all the virtual resources:

    ./remove-hypervisor-virtual

Note that this will still leave the network and the downloaded virtual machine images intact. You
can make sure to completely remove _all_ virtual resources by using `-f`:

    ./remove-hypervisor-virtual -f

You may need to run with `-f` several times until it completes successfully because some resources
might be in an indeterminate state when you run.
