Chapter 3: OpenStack
====================

As mentioned in chapter 2, OpenStack is modular such that each participating machine may have a
different role. For the purpose of this lab our "compute" role will have its own dedicated hardware,
while the "controller" role will live on the Manager as a virtual machine.

> Note that it is technically possible for the "compute" role to also be a virtual machine, such
that our entire OpenStack deployment would run on a single physical machine. Though it would work,
it would introduce an unwanted side effect: our OpenStack workloads would be running in *nested
virtualization*. This advanced feature has various limitations and is often accompanied by a
significant hit to performance. For this reason we are installing the "compute" role on dedicated
hardware.


Step 1: Prepare the infrastructure
----------------------------------

Before we introspect our infrastructure (in the next step) we need to create the extra virtual
machines that will be part of it and also prepare the operating system images that will used by all
infrastructure machines during the introspection process, as well as different images that will
be used to install the OpenStack services on them (in step 3).

    openstack/infrastructure/prepare

What [this script](../openstack/infrastructure/prepare) does:

* Creates operating system images that TripleO will use to introspect and provision the
  infrastructure nodes using PXE
* Creates a virtual machine named `openstack-controller` configured by the files in 
  [`configuration/libvirt/domains/openstack-controller/`](../configuration/libvirt/domains/openstack-controller/)

The bulk of the work in this step will be handled by `openstack overcloud image build`, which
can take a while to complete, ~ 5 minutes.

> It's also possible to download ready-made images from the RDO project. From our experience the
repository is rather slow and does not offer an advantage over building them locally.

After it's done we can see that the images have been uploaded into TripleO:

	manager/tripleo/openstack image list

In TripleO's `tripleo` user's home directory:

* `ironic-python-agent.kernel` and `ironic-python-agent.initramfs` are
  small images used by TripleO's Ironic for introspection
* `overcloud-full.qcow2` and `overcloud-full.initrd` are the OpenStack
  installation images

Logs and configuration files have been fetched to the `workspace/results/` directory. Some useful
ones are from:

* Manager: `/var/log/libvirt/qemu/openstack-controller.log`
* Manager: `/var/log/virtualbmc/virtualbmc.log`
* TripleO: `ironic-python-agent.log`
* TripleO: `overcloud-full.log`

Note that when creating the `openstack-controller` virtual machine we also enable
[VirtualBMC](https://docs.openstack.org/virtualbmc/latest/) to access it. This is necessary because
TripleO, our OpenStack infrastructure manager, does not inherently support virtual machines as part
of the infrastructure due to its reliance on Ironic. VirtualBMC will thus provide an 
[IPMI](https://en.wikipedia.org/wiki/Intelligent_Platform_Management_Interface) to the virtual
machine so that it could be remote controlled like a physical machine.

We can test this using [ipmitool](https://github.com/ipmitool/ipmitool), which we installed for this
purpose on the Manager in the previous chapter. Use [this shortcut](../manager/ipmitool):

    manager/ipmitool 6230 power status

The first argument is the IPMI port: each virtual machine supported by VirtualBMC gets its own
dedicated port. 6230 is the port we configured for `openstack-controller`. We also have a
[shortcut](../manager/vbmc) to VirtualBMC's client CLI:

    manager/vbmc list


Step 2: Introspect the infrastructure
-------------------------------------

Our infrastructure is not yet ready for deploying OpenStack on it. We must first "introspect" our
infrastructure nodes, which in our case are the physical "compute" node and the virtual
"controller" node:

    openstack/infrastructure/introspect

The bulk of the work of this [this script](../openstack/infrastructure/introspect) is handled by the
`openstack overcloud node introspect` command. It is configured
by
[`configuration/openstack/infrastructure-inventory.yaml`](../configuration/openstack/infrastructure-inventory.yaml).

During introspection each node is provisioned the `ironic-python-agent` minimal operating system
image via PXE (which we prepared in the previous step), which boots up and reports back to TripleO
with a detailed profile of its hardware. TripleO will store this profile in its database.

This can take a while, 15 minutes and more. How long exactly depends on our hardware.

While it runs it could be useful to see the changing state of the infrastructure nodes. We can
set up a `watch` like so:

    watch manager/tripleo/openstack baremetal node list

We should see the nodes powering on, then changing their provisioning state from "enroll" to
"verifying" to "manageable". (If we set `clean_nodes` to true in `undercloud.conf` then we will
also see "cleaning" and "clean wait".) When introspection finishes successfully for all nodes they
will be set at once to "available".

manager/tripleo/openstack overcloud profiles list

> TODO: machines without IPMI. "pm_type: manual-management". need monitor-keyboard-mouse.

Logs and configuration files have been fetched to the `workspace/results/` directory. Some useful
ones are from:

* TripleO: `/home/tripleo/introspection/` has the introspection results in JSON
* TripleO: `/var/log/containers/ironic/ironic-conductor.log`
* TripleO: `/var/log/containers/ironic-inspector/ironic-inspector.log`
* TripleO: `/var/log/containers/ironic-inspector/ramdisk/` contains `tar.gz` files for each
  infrastructure node workflow, which internally contain the `journal` of the introspection process
* TripleO: `/var/log/containers/mistral/engine.log`
* TripleO: `/var/log/containers/heat/heat-engine.log`

In TripleO's `tripleo` user's home directory:

* `/home/tripleo/infrastructure-nodes.yaml` copied from
  `configuration/tripleo/infrastructure-nodes.yaml`


Step 3: Deploy OpenStack
------------------------

We can now finally deploy OpenStack on our infrastructure:

    openstack/deploy

Deployment is handled by the `openstack overcloud deploy` command. It is configured by the files in
`configuration/overcloud/`.

During installation each infrastructure node is assigned a "role" and is provisioned with an
operating system image via PXE (which we prepared in step 1). After the operating systems boots, the
process continues similarly to how it worked with TripleO (the undercloud) in the previous chapter.
The main difference is that our undercloud is an all-in-one OpenStack installation while our
overcloud has different sets of OpenStack services deployed per machine according to its role. So,
let's repeat what we said about the TripleO deployment: 

Internally it will be using [Puppet](https://puppet.com/) to orchestrate the installation and
configuration of the various OpenStack services as containers to be run by
[Podman](https://podman.io/). Containers allow for better isolation and portability. The undercloud
itself is installed using the OpenStack [Heat](https://docs.openstack.org/heat/latest/)
orchestration and [Mistral](https://docs.openstack.org/mistral/latest/) workflow services, which
internally use [Ansible](https://www.ansible.com/). The OpenStack container images are provided by
the [Kolla project](https://docs.openstack.org/kolla/latest/).

Our OpenStack storage is handled by [Ceph](https://ceph.com/) and its deployment is handled by yet
another project, [Ceph-Ansible](http://docs.ceph.com/ceph-ansible/), which provides its own
container images.

> In production deployments we would likely have dedicated storage machines, indeed different kinds
according to the various Ceph roles. But that is unnecessary for our lab, where it would be fine to
have our single machine provide both compute and storage resources. Thus we will be deploying a
[hyper-converged infrastructure (HCI)](https://en.wikipedia.org/wiki/Hyper-converged_infrastructure)
version of the "Compute" role, named "ComputeHCI". We will even be fine-tuning Ceph for optimal
performance for this converged setup.  

TODO: explain networking, OVS, OVN

All off this takes a while. Expect TODO 

As in the previous step, it could also be useful to see the changing state of the infrastructure
nodes. We can set up a `watch` like so:

    watch manager/tripleo/openstack baremetal node list

We should see the nodes getting an "Instance UUID" and then changing their provisioning
state from "available" to "deploying". They should then power on and change to "wait call-back".
As they start to PXE boot the state will go back to "deploying" and finally "active" when they are
fully installed.

At this point the overcloud servers will also be up. We can simultaneously set up yet another watch
for them:

    watch manager/tripleo/openstack server list

Their initial status will be "BUILD" and eventually switch to "ACTIVE" and they will receive network
IP addresses.

Note that the server names are *not* the same as the infrastructure node names: this is where the
difference between undercloud and overcloud becomes clear. The server names comprise the Heat stack
name ("lab"), the role name, and a sequenced ID beginning with "0". So, our first and only
controller would be `lab-controller-0`, and storage-converged compute node would be
`lab-computehci-0`.

After deployment is done we will find some useful files in the `tripleo` virtual machine at the
`tripleo` user's home directory: 

* `/home/tripleo/overcloud-container-images.yaml` was generated by us calling
   `openstack tripleo container image prepare`
* `/home/tripleo/heat-environments.yaml` copied from
  `configuration/openstack/heat-environments.yaml` and referencing the above file

*

Logs and configuration files have been fetched to the `workspace/results/` directory. Some useful
ones are from:

`/var/lib/mistral/lab/ansible.log`

`/var/lib/mistral/lab/ceph-ansible/ceph_ansible_command.log`

* TripleO: `/var/log/containers/ironic/deploy/` contains `tar.gz` files for each infrastructure node
  workflow, which internally contain the `journal` of the installation process


TODO tail this file:
/var/lib/mistral/overcloud/ansible.log

manager/tripleo/openstack baremetal node undeploy compute-0

openstack/openstack user list

openstack/openstack stack failures list

The `openstack` command is documented
[here](https://docs.openstack.org/python-openstackclient/stein/cli/).


MISSING PIECES FROM ABAYS

tripleo:
sudo ip r add 10.0.0.0/24 dev br-ctlplane

controller:
sudo ovs-vsctl remove port vlan10 tag 10

manager:
sudo ip a add 10.0.0.69/24 dev openstack


https://access.redhat.com/documentation/en-us/red_hat_openstack_platform/8/html/ipv6_networking_for_the_overcloud/configuring_the_overcloud_before_creation

tripleo
sudo ovs-vsctl add-port br-ctlplane vlan10 tag=10 -- set interface vlan10 type=internal
sudo ip l set dev vlan10 up
...
sudo ovs-vsctl del-port vlan10


in `/var/lib/mistral/lab/ceph-ansible/ceph_ansible_command.log`
podman pull failed


openstack compute service list



controller:
sudo ovs-vsctl add-port br-public eth2
sudo ip addr add 10.0.2.2 dev br-public



	#openstack stack resource list overcloud
	#openstack stack resource show overcloud ControllerServiceChain



sudo tcpdump -i br-ex -nn -e vlan | grep "vlan 50"






Installing the Cloud
====================

If we're installing an all-in-one setup, then we should already have the cloud virtual machines set
up for us from the previous step: `controller-0`, `compute-0`, and `ceph-0`. In RDO, each cloud
machine is assigned a role that defines which OpenStack components run on it:

* Controller:
  Manages networking ([Neutron](https://docs.openstack.org/neutron/latest/)) as well
  as virtual machine scheduling
  ([nova-scheduler](https://docs.openstack.org/nova/latest/cli/nova-scheduler.html)).
  It requires only minimal compute and disk resources. The defaults should suffice.
* Compute: [nova-compute](https://docs.openstack.org/nova/latest/cli/nova-compute.html). This is
  where our cloud virtual machines will be provisioned (in nested virtualization). So, we want this
  machine to be alloted a lot of RAM and CPU cores.
* Ceph: [Ceph](https://ceph.com/) is a powerful distributed storage system with good OpenStack
  integration. This is where our
  block storage ([Cinder](https://docs.openstack.org/cinder/latest/)),
  file storage ([Manila](https://docs.openstack.org/manila/latest/)),
  and object storage ([Swift](https://docs.openstack.org/swift/latest/)) will be provisioned.
  So, on the lab we want this machine to be alloted a lot of disk space. RAM and CPU defaults
  should suffice.

> One interesting implementation detail: if you remember, our cloud manager uses OpenStack's
[Ironic](https://wiki.openstack.org/wiki/Ironic) component to manage the cloud machines. You might
think that it only uses Ironic for bare metal machines, which is what it was designed for. In the
all-in-one setup we are using virtual machines, we shouldn't have to use Ironic, right?
In fact, we are using Ironic for all machines, whether bare metal or virtual. We do this in order to
maintain a single management path for all machines. This works well, but it does involve some
cunning to make the virtual machines behave more like bare metal. To learn more about this
technology see [VirtualBMC](https://github.com/openstack/virtualbmc), which exposes an
[IPMI](https://en.wikipedia.org/wiki/Intelligent_Platform_Management_Interface).



Step 3: Prepare cloud
---------------------

Now we have an OpenStack instance, but it's still very bare. Let's add the basics:

    ./prepare-cloud

This will create:

* A `public` network in the `admin` project (subnet 10.0.0.0/24) 
* Conventional public flavors, such `m1.tiny` and `m1.large`
* Common images, such as `common.centos7` in the `common` project


Accessing the Cloud
-------------------

Access details for the `admin` user on the `admin` proect were added to our InfraRed workspace on
the Manager. We provide `openstack` as a shortcut script. Example:

    ./openstack network list

Another useful shortcut is `openstack-project`, which uses the `admin` user on a different project:

    ./openstack-project my-project server list

Note that if you create your own project, it does not by default grant the `admin` user access to
it. To grant access:

    ./openstack project create my-project --parent common
    ./openstack role add admin --project my-project --user admin


Quick Test
----------

We have a script to create a "hello world" example:

    ./create-simple-project test hello-world

This creates a `test` project with its own `test.private` network, subnet, and router that used the
`public` network as its external gateway. We make sure the project's `default` security group rules
allow for ping (ICMP) and ssh. We then create a server named `hello-world` with a new `test`
keypair, create and attach a 2 GB volume to it, and finally assign it a floating IP (again on the
`public` network).

You can ssh into the fully functioning virtual machine using the private key, e.g.:

    ./ssh-virtual -i ~/openstack-keypairs/test centos@10.0.0.210

You must manually format and mount the attached volume:

    sudo mkfs.ext4 /dev/vdb
    sudo mount /dev/vdb /mnt

When done testing, you can delete the project and all its resources using our `delete-project`
script:

    ./delete-project test

Note that deleting a project is tricky in OpenStack, because the simple `openstack project delete`
command will *not* delete associated resources and instead leave them orphaned and dangling. It's
likewise tricky to delete networks, because the operation will fail if ports on the network are in
use. Yet another issue is that ports on the network can be created in *other* projects. This script
does the heavy lifting to ensure that all resources associated with the project are safely deleted.


How to Reset
------------

Note that we cannot do this with the `openstack-undercloud` shortcut, because we need elevated
credentials in order to access the overcloud.

    ./ssh-virtual stack@undercloud-0
    . stackrc
    openstack overcloud delete overcloud
