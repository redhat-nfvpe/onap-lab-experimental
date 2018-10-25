Installing the Cloud
====================

Step 1: Install cloud images
----------------------------

Our cloud manager ("undercloud") provides operating system images for bootstrapping the cloud
machines. We need to install them. On Orchestrator:

    ./build-undercloud-images

Another option, which is a bit faster, is to download ready-made images. However, we cannot
guarantee that they will be identical to the built images. To import:

    ./download-undercloud-images

To list the images, on Hypervisor:

    ./openstack-undercloud image list

On `undercloud-0` you'll find useful logs for this step:

    /home/stack/overcloud-full.log
    /home/stack/openstack-build-images.log
    /home/stack/ironic-python-agent.log


Step 2: Install cloud machines
------------------------------

If we're installing an all-in-one setup, then we should already have the cloud virtual machines set
up for us from the previous step: `controller-0`, `compute-0`, and `ceph-0`. In RDO, each cloud
machine is assigned a role that defines which OpenStack components run on it:

* Controller:
  Manages networking ([Neutron](https://docs.openstack.org/neutron/queens/)) as well
  as virtual machine scheduling
  ([nova-scheduler](https://docs.openstack.org/nova/queens/cli/nova-scheduler.html)).
  It requires only minimal compute and disk resources. The defaults should suffice.
* Compute: [nova-compute](https://docs.openstack.org/nova/queens/cli/nova-compute.html). This is
  where our cloud virtual machines will be provisioned (in nested virtualization). So, we want this
  machine to be alloted a lot of RAM and CPU cores.
* Ceph: [Ceph](https://ceph.com/) is a powerful distributed storage system with good OpenStack
  integration. This is where our
  block storage ([Cinder](https://docs.openstack.org/cinder/queens/)),
  file storage ([Manila](https://docs.openstack.org/manila/queens/)),
  and object storage ([Swift](https://docs.openstack.org/swift/queens/)) will be provisioned.
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

Let's install them:

    ./install-overcloud

On `undercloud-0` you'll find useful logs and topology files for this step:

    /home/stack/overcloud_install.log
    /home/stack/overcloud_deployment_44.log
    /home/stack/openstack_failures_long.log
    /home/stack/instackenv.json

The root user at the Hypervisor (and also in `undercloud-0`) now has a keypair (at `/root/.ssh`)
that can be used to login as user `heat-admin` to the cloud machines, which has sudo access there.
To login, you need to find their addresses, which you can see with the `openstack server info`
command. We provide `ssh-undercloud` as a shortcut script. An example:  

    ./ssh-undercloud compute-0

Within each cloud machine we will be running the OpenStack components as Docker containers. This
allows for better isolation, stability, and an easier upgrade path. Internally,
[Kolla](https://docs.openstack.org/kolla/queens/) is used to deploy the container images. To see the
containers from within a cloud machine:

    sudo docker container list


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

    ./create-hello-world

This creates a `test` project with its own network, subnet, and router that used the `public`
network as its external gateway. We make sure the project's `default` security group rules allow for
ping (ICMP) and ssh. We then create a server named `hello-world` with a new `test` keypair and
assign it a floating IP (again on the `public` network). Give the server a minute or two to startup,
and then you can ssh into the fully functioning virtual machine using the private key, e.g.:

    ./ssh-virtual -i ~/openstack-keypairs/test centos@10.0.0.210

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
