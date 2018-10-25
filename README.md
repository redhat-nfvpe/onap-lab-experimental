**THIS IS AN EXEPERIMENT. PLEASE DO NOT USE.**

Red Hat ONAP Lab
================

Create a reusable, reproducible lab for running and developing on ONAP on top of a supportable
stack of Linux, OpenStack, and Kubernetes.

This documentation is lengthy. Our goal here is to help you understand and debug each step so that
you can own and administer the lab.


Supported Starting Points
-------------------------

* All you have is bare metal: This guide will take you from zero to ONAP. The entire lab can be
  installed on a single physical machine. Depending on your requirements, you can also spread it out
  on several physical machines.  
* You already have a Kubernetes cluster: Start with chapter 5.
* You already have an OpenStack cloud: Start with chapter 4.

For a single-physical-machine lab you do need hefty server-class or workstation hardware. A great
budget solution is to buy a used workstation, such as a Dell Precision T7600 or an HP Z820 from
2012-13. They come with up to 256GB of RAM, 16 cores, and plenty of space for storage drives.


Software Layers
---------------

The full lab comprises 3 platform layers:

* [ONAP](https://www.onap.org/) itself: A large set of containers running on a
  [Kubernetes](https://kubernetes.io/) cluster. The initial deployment is configured via a
  [Helm](https://helm.sh/) chart. 
* [OKD](https://www.okd.io/): Manages the Kubernetes cluster. This includes tenants, storage,
  networks, a container image registry ([Quay](https://www.openshift.com/products/quay)), and a
  CI/CD pipeline. Red Hat provides a supported version of OKD called
  [OpenShift](https://www.openshift.com/).
* [RDO](https://www.rdoproject.org/): OpenStack distribution.
  Red Hat provides a supported version of RDO in its
  [OpenStack Platform](https://www.redhat.com/en/technologies/linux-platforms/openstack-platform).
  We will be doing a comprehensive, full-featured installation of RDO that gives you a
  straightforward upgrade path to a very large lab environment, with the same tooling you would
  have in staging and even production environments.  

Note that it is possible to avoid OpenStack and run OKD directly on bare metal. However, we find
that in a lab environment it is useful to have OKD hosted inside OpenStack-managed virtual machines.
Thi allows us to more easily set up and tear down OKD and run multiple OKD clusters (even of
different versions) simultaneously.

Furthermore, because we need an OpenStack cloud to run ONAP integration tests (ONAP will orchestrate
VNFs there), we might as well use it to host OKD and ONAP itself.

As OKD bare metal support matures we will provide that installation option here.


Physical Machines
-----------------

The lab comprises 3 physical machines roles:

* Orchestrator: This is the machine on which we execute the Ansible playbooks that set up the lab.
  It can be any Unix-like machine with Python 2.7.
* Hypervisor: This is the machine that manages and bootstraps our cloud machines. It *must* run
  CentOS or RHEL and be capable of supporting a few virtual machines.
* Cloud: One or more machines that will provide physical resources for OpenStack to manage and
  provision. Actually, within the cloud role there are various sub-roles: compute, storage, etc.
  From this high-level, though, they are managed in the same way. 

All 3 roles can definitely be combined into a single physical machine, which we'll call the
"all-in-one" setup. We strongly recommend the all-in-one setup for newcomers, as it is significantly
easier to install and administer.

If you are combining the Hypervisor and Cloud roles into one machine, it may make sense to have both
SSD and HDD drives in it. The Hypervisor software has a finite size and its storage can fit on the
SSD. One or more large HDDs can be reserved for cloud storage.


Chapters
--------

1. [Preparing the Orchestrator](doc/orchestrator.md)
2. [Preparing the Hypervisor](doc/hypervisor.md)
3. [Installing the Cloud](doc/cloud.md)
4. [Installing Kubernetes](doc/kubernetes.md)
5. [Scheduling ONAP](doc/onap.md)


Special Thanks
--------------

The following people may not show up in the commit history, but helped on the way:

* Ruslan Usichenko
* Andrew Bays
* Yolanda Robla Mota
* Frank Zdarsky
* Leif Madsen
