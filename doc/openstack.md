Chapter 3: Install OpenStack
============================

As mentioned in chapter 2, OpenStack is modular such that each participating machine may have a
different role. For the purpose of this lab our "compute" role will have its own dedicated hardware,
while the "controller" role will live on the Hypervisor as a virtual machine.

> Note that it is technically possible for the "compute" role to also be a virtual machine, such
that our entire OpenStack deployment would run on a single physical machine. Though it would work,
it would introduce an unwanted side effect: if we want to deploy virtualized workloads on top of
OpenStack, such as VNFs, they would be running in *nested virtualization*. This advanced feature has
various limitations and is often accompanied by a significant hit to performance. Thus, to avoid
nested virtualization we are installing the "compute" role on dedicated hardware.


Step 1: Prepare the infrastructure
----------------------------------

Before we introspect our infrastructure (in the next step) we need to create the extra virtual
machines that will be part of it and also prepare the operating system images that will used by all
infrastructure machines during the introspection process, as well as different images that will
be used to install the OpenStack services on them (in step 3).

    openstack/infrastructure/prepare

What this script does:

* Creates operating system images that TripleO will use to introspect and provision the
  infrastructure nodes using PXE
* Creates a virtual machine named `openstack-controller` configured by 
  `configuration/libvirt/domains/openstack-controller/virt-install.ini`

The bulk of the work in this step will be handled by `openstack overcloud image build`, which
can take a while to complete, ~ 5 minutes.

After it's done we will find some more files under our `workspace/` directory:

* `workspace/keys/stack@openstack-controller` and `workspace/keys/stack@openstack-controller.pub`
  are they keypair for the virtual machine
* `workspace/passwords/stack@openstack-controller` is the password
* `workspace/ssh.config` is updated for `tripleo-stack`

Logs and configuration files have been fetched to the `workspace/results/` directory. Some useful
ones are from:

* Hypervisor: `/var/log/libvirt/qemu/openstack-controller.log`
* Hypervisor: `/var/log/virtualbmc/virtualbmc.log`

In the Hypervisor's `stack` user's home directory:

* `/home/stack/keys/stack@openstack-controller` and `/home/stack/stack@openstack-controller.pub`
* `/home/stack/libvirt/images/openstack-controller.qcow2` is our virtual machine drive image

In TripleO's `stack` user's home directory:

* `/home/stack/ironic-python-agent.kernel` and `/home/stack/ironic-python-agent.initramfs` are
  small images used by TripleO's Ironic for introspection
* `/home/stack/ironic-python-agent.log` is the log for building the above
* `/home/stack/overcloud-full.qcow2` and `/home/stack/overcloud-full.initrd` are the OpenStack
  installation images
* `/home/stack/overcloud-full.log` is the log for building the above

Note that when creating the `openstack-controller` virtual machine we also enable
[VirtualBMC](https://docs.openstack.org/virtualbmc/latest/) to access it. This is necessary because
TripleO, our OpenStack infrastructure manager, does not inherently support virtual machines as part
of the infrastructure due to its reliance on Ironic. VirtualBMC will thus provide an 
[IPMI](https://en.wikipedia.org/wiki/Intelligent_Platform_Management_Interface) to the virtual
machine so that it could be remote controlled like a physical machine.

We can test this using [ipmitool](https://github.com/ipmitool/ipmitool), which we installed for this
purpose on the Hypervisor in the previous chapter. Use this shortcut:

    hypervisor/ipmitool 6230 power status

The first argument is the IPMI port: each virtual machine supported by VirtualBMC gets its own
dedicated port. 6230 is the port we configured for `openstack-controller`.


Step 2: Introspect the infrastructure
-------------------------------------

Our infrastructure is not yet ready for installing OpenStack. We must first "introspect" our
infrastructure nodes, which in our case are the physical "compute" node and the virtual
"controller" node:

    openstack/infrastructure/introspect

Introspection is handled by the `openstack overcloud node introspect` command. It is configured
by `configuration/tripleo/infrastructure-nodes.yaml`.

During introspection each node is provisioned a minimal operating system image via PXE (which we
prepared in the previous step), which boots up and reports back to TripleO with a detailed profile
of its hardware. TripleO will store this profile in its database.

This can take a while, 15 minutes and more. How long exactly depends on your hardware.

While it runs it could be useful to see the changing state of the infrastructure nodes. We can
set up a `watch` like so:

    watch hypervisor/tripleo/openstack baremetal node list

We should see the nodes powering on, then changing their provisioning state from "enroll" to
"manageable". When introspection finished successfully for all nodes they will all be changed at
once to "available".

> TODO: machines without IPMI. "pm_type: manual-management". need monitor-keyboard-mouse.

Logs and configuration files have been fetched to the `workspace/results/` directory. Some useful
ones are from:

* TripleO: `/var/log/containers/ironic/ironic-conductor.log`
* TripleO: `/var/log/containers/ironic-inspector/ironic-inspector.log`
* TripleO: `/var/log/containers/ironic-inspector/ramdisk/` contains `tar.gz` files for each
  infrastructure node workflow, which internally contain the `journal` of the introspection process
* TripleO: `/var/log/containers/mistral/engine.log`
* TripleO: `/var/log/containers/heat/heat-engine.log`

In TripleO's `stack` user's home directory:

* `/home/stack/infrastructure-nodes.yaml` copied from
  `configuration/tripleo/infrastructure-nodes.yaml`


Step 3: Install OpenStack
-------------------------

We can now finally install OpenStack on our infrastructure:

    openstack/install

As in the previous step, while it runs it could be useful to see the changing state of the
infrastructure nodes. We can set up a `watch` like so:

    watch hypervisor/tripleo/openstack baremetal node list

* `/home/stack/overcloud-container-images.yaml` was generated by us calling
   `openstack tripleo container image prepare`
* `/home/stack/overcloud-deploy-answers.yaml` copied from
  `configuration/tripleo/overcloud-deploy-answers.yaml` and referencing the above file

We should see the nodes getting an "Instance UUID" and then changing their provisioning
state from "available" to "deploying". They should then power on and change to "wait call-back".
As they start to network boot it would go back to "deploying" and finally "active" when they are
fully installed.

After it's done we will find some useful files in the `tripleo` virtual machine at the `stack`
user's home directory: 

*

Useful service logs on the `tripleo` virtual machine:

* `/var/log/containers/ironic/deploy/` contains `tar.gz` files for each infrastructure node
  workflow, which internally contain the `journal` of the installation process

TODO

hypervisor/tripleo/openstack baremetal node undeploy compute-0
























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
the Hypervisor. We provide `openstack` as a shortcut script. Example:

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
