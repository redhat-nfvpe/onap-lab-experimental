Installing the Cloud
====================

Step 1: Build cloud images
--------------------------

Our cloud manager ("undercloud") provides operating system images for bootstrapping the cloud
machines. We need to install them. On Orchestrator:

	./build-cloud-images

Another option, which is a bit faster, is to download ready-made images. However, we cannot
guarantee that they will be identical to the built images. To import:

	./download-cloud-images

To see the images, on Hypervisor:

	sudo ssh undercloud-0
	. stackrc
	openstack image list

On `undercloud-0` you'll find useful logs for this step:

	/home/stack/openstack-build-images.log
	/home/stack/ironic-python-agent.log


Step 2: Install cloud machines
------------------------------

If we're installing an all-in-one setup, then we should already have the cloud virtual machines set
up for us from the previous step: `controller-0` and `compute-0`. In RDO, each cloud machine is
assigned a role that defines which OpenStack components run on it:

* Controller:
  [Neutron](https://docs.openstack.org/neutron/queens/) +
  [nova-scheduler](https://docs.openstack.org/nova/queens/cli/nova-scheduler.html)
* Compute: [nova-compute](https://docs.openstack.org/nova/queens/cli/nova-compute.html). This is
  where our cloud virtual machines will run (nested virtualization). So, we want this machine to be
  alloted a lot of RAM and CPUs.

> One interesting implementation detail: if you remember, our cloud manager uses OpenStack's
[Ironic](https://wiki.openstack.org/wiki/Ironic) component to manage the cloud machines. You might
think that it only uses Ironic for bare metal machines, which is what it was designed for. Because
in the all-in-one setup we are using virtual machines, we shouldn't have to use Ironic, right?
Surprisingly, we are! We do this in order to maintain a single management path for all machines,
whether they are bare metal or virtual. This works well, but it does involve some cunning to make
the virtual machines behave more like bare metal. To learn more about this technology, see
[VirtualBMC](https://github.com/openstack/virtualbmc), which exposes an
[IMPI](https://en.wikipedia.org/wiki/Intelligent_Platform_Management_Interface) for Ironic.

Let's install them:

	./install-overcloud

Within each cloud machine we will be running the OpenStack components as Docker containers. This
allows for better isolation, stability, and an easier upgrade path.

TODO: log in to them and see the Docker containers

On `undercloud-0` you'll find useful logs:

	/home/stack/overcloud_install.log
	/home/stack/overcloud-full.log
	/home/stack/overcloud_deployment_44.log
	/home/stack/openstack_failures_long.log
	/home/stack/instackenv.json

https://rdo-container-registry.readthedocs.io/en/latest/using.html
https://docs.openstack.org/tripleo-docs/latest/contributor/dlrn-promoter-overview.html
