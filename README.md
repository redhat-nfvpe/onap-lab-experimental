**THIS IS AN EXEPERIMENT. PLEASE DO NOT USE.**

Red Hat ONAP Lab
================

Create a reusable, reproducible, opinionated lab for running and developing on ONAP on top of a
supportable stack of Linux (CentOS or RHEL), OpenStack (RDO or RHOSP), and Kubernetes (OKD or
OpenShift).

This documentation is lengthy. Our goal here is to help you examine and understand each step so that
you can own and administer your lab.


Supported Starting Points
-------------------------

* Starting from just hardware, this guide will take us from zero to ONAP. At minimum the lab
  requires two physical machines. Note that the resource requirements for ONAP are
  [hefty](https://wiki.onap.org/display/DW/Minimal+Assets+for+Physical+Lab), especially for RAM.
  We would need server-class or workstation hardware. (A great budget solution is to buy used
  workstations, such as Dell Precision T7600 or HP Z820, which is hardware from 2012-13. They come
  with up to 256GB of RAM, 16 cores, and plenty of space for storage drives.)
* If we already have an OpenStack cloud then start with chapter 4.
* If we already have a robust Kubernetes cluster then start with chapter 5.


Software Layers
---------------

The full lab comprises 3 platform layers:

* [ONAP](https://www.onap.org/) itself: A large set of containers running on a
  [Kubernetes](https://kubernetes.io/) cluster. The initial deployment is configured via a
  [Helm](https://helm.sh/) chart. 
* [OKD](https://www.okd.io/): Kubernetes distribution and cluster management. This includes tenants,
  storage, networks, a container image registry ([Quay](https://www.openshift.com/products/quay)),
  and a CI/CD pipeline. Red Hat's supported version of OKD is
  [OpenShift](https://www.openshift.com/).
* [RDO](https://www.rdoproject.org/): OpenStack distribution.
  Red Hat's supported version of RDO is
  [Red Hat OpenStack Platform (RHOSP)](https://www.redhat.com/en/technologies/linux-platforms/openstack-platform).
  We will be doing a comprehensive, full-featured installation of RDO that gives us an upgrade path
  to staging and even production environments.  

Note that instead of Kubernetes-on-OpenStack layering it is also possible to run Kubernetes and
OpenStack side by side (Kubernetes on bare metal). However, we find that especially in a lab
environment it is useful to have the Kubernetes cluster managed by OpenStack so that we can more
easily tear it down and set it up again, or run multiple clusters (even different versions) side by
side.


Physical Machines
-----------------

The lab comprises 3 physical machines roles:

* Orchestrator: This is the machine we will use to run the scripts to remotely orchestrate the lab.
  We will just be using bash, ssh, and a few extra utilities, so any Unix-like machine should do.
* Manager: This is the machine that manages and bootstraps our cloud machines. It must have CentOS
  (or RHEL) and be capable of supporting a few virtual machines.
* Cloud: One or more machines that will provide the cloud resources for OpenStack to provision and
  manage. Actually, within the cloud role there are various sub-roles, such as compute, storage,
  etc., but for simplicity we will be running them as "hyper-converged": compute plus storage.
  At the minimum these machines must be able to PXE boot, but ideally they would have
  [IPMI](https://en.wikipedia.org/wiki/Intelligent_Platform_Management_Interface) or any of the
  other management technologies supported by
  [Ironic](https://docs.openstack.org/ironic/latest/admin/drivers.html). Note that ONAP is a RAM-
  and storage-hungry workload, so our cloud machine(s) should have plenty of each.


Chapters
--------

1. [Prepare the Orchestrator](doc/orchestrator.md)
2. [Prepare the Manager](doc/manager.md)
3. [Install OpenStack](doc/openstack.md)
4. [Install Kubernetes](doc/kubernetes.md)
5. [Install ONAP](doc/onap.md)


Special Thanks
--------------

The following people may not show up in the commit history but deserve credit for contributing:

* Aaron Smith
* Andrew Bays
* Frank Zdarsky
* Leif Madsen
* Ruslan Usichenko
* Yolanda Robla Mota
