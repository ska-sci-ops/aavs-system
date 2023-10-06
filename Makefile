#
# Project makefile for a SKA AAVS-SYSTEM project.
#
# Distributed under the terms of the BSD 3-clause new license.
# See LICENSE for more info.
#
PROJECT = aavs-system

include .make/oci.mk
include .make/python.mk
include .make/raw.mk
include .make/base.mk
include .make/docs.mk
include .make/helm.mk
include .make/k8s.mk
include .make/tmdata.mk
include .make/xray.mk

# define private overrides for above variables in here
-include PrivateRules.mak