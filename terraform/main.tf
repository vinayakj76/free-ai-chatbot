terraform {
  required_providers {
    oci = {
      source  = "oracle/oci"
      version = ">= 4.0.0"
    }
  }
}

# --- Variables ---
variable "tenancy_ocid" {}
variable "user_ocid" {}
variable "fingerprint" {}
variable "private_key_path" {}
variable "region" {}

variable "compartment_ocid" {
  description = "The OCID of the compartment where resources will be created"
}

variable "ssh_public_key" {
  description = "Your public SSH key (e.g., content of ~/.ssh/id_rsa.pub)"
}

variable "instance_shape" {
  default = "VM.Standard.A1.Flex"
}

variable "instance_ocpus" {
  default = 4 # Max for Free Tier
}

variable "instance_memory_in_gbs" {
  default = 24 # Max for Free Tier
}

# --- Provider Configuration ---
provider "oci" {
  tenancy_ocid     = var.tenancy_ocid
  user_ocid        = var.user_ocid
  fingerprint      = var.fingerprint
  private_key_path = var.private_key_path
  region           = var.region
}

# --- Networking ---
resource "oci_core_vcn" "free_tier_vcn" {
  cidr_block     = "10.0.0.0/16"
  compartment_id = var.compartment_ocid
  display_name   = "FreeTier-VCN"
  is_ipv6enabled = false
}

resource "oci_core_internet_gateway" "free_tier_ig" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.free_tier_vcn.id
  display_name   = "FreeTier-IG"
}

resource "oci_core_route_table" "free_tier_rt" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.free_tier_vcn.id
  display_name   = "FreeTier-RouteTable"

  route_rules {
    destination       = "0.0.0.0/0"
    destination_type  = "CIDR_BLOCK"
    network_entity_id = oci_core_internet_gateway.free_tier_ig.id
  }
}

# Security List (Firewall) - Opens SSH, HTTP, and Custom Ports
resource "oci_core_security_list" "free_tier_sl" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.free_tier_vcn.id
  display_name   = "FreeTier-SecurityList"

  // Allow incoming SSH
  ingress_security_rules {
    protocol = "6" // TCP
    source   = "0.0.0.0/0"
    tcp_options {
      min = 22
      max = 22
    }
  }

  // Allow incoming HTTP (Port 80)
  ingress_security_rules {
    protocol = "6"
    source   = "0.0.0.0/0"
    tcp_options {
      min = 80
      max = 80
    }
  }

  // Allow incoming Streamlit/FastAPI (Port 8501 or 8000)
  ingress_security_rules {
    protocol = "6"
    source   = "0.0.0.0/0"
    tcp_options {
      min = 8501
      max = 8501
    }
  }

  // Allow all outgoing traffic
  egress_security_rules {
    protocol    = "all"
    destination = "0.0.0.0/0"
  }
}

resource "oci_core_subnet" "free_tier_subnet" {
  cidr_block        = "10.0.0.0/24"
  compartment_id    = var.compartment_ocid
  vcn_id            = oci_core_vcn.free_tier_vcn.id
  display_name      = "FreeTier-Subnet"
  route_table_id    = oci_core_route_table.free_tier_rt.id
  security_list_ids = [oci_core_security_list.free_tier_sl.id]
  dhcp_options_id   = oci_core_vcn.free_tier_vcn.default_dhcp_options_id
}

# --- Compute Instance ---
# Data source to get the latest Oracle Linux 8 Image (Compatible with Free Tier)
data "oci_core_images" "oracle_linux_images" {
  compartment_id           = var.compartment_ocid
  operating_system         = "Oracle Linux"
  operating_system_version = "8"
  shape                    = var.instance_shape
  sort_by                  = "TIMECREATED"
  sort_order               = "DESC"
}

locals {
  image_id = data.oci_core_images.oracle_linux_images.images[0].id
}

resource "oci_core_instance" "free_tier_instance" {
  availability_domain = data.oci_identity_availability_domains.ads.availability_domains[0].name
  compartment_id      = var.compartment_ocid
  display_name        = "AI-Instance"
  shape               = var.instance_shape

  shape_config {
    ocpus         = var.instance_ocpus
    memory_in_gbs = var.instance_memory_in_gbs
  }

  create_vnic_details {
    subnet_id      = oci_core_subnet.free_tier_subnet.id
    assign_public_ip = true
  }

  source_details {
    source_id   = local.image_id
    source_type = "image"
  }

  metadata = {
    ssh_authorized_keys = var.ssh_public_key
  }
}

# --- Data Source to get ADs ---
data "oci_identity_availability_domains" "ads" {
  compartment_id = var.tenancy_ocid
}

# --- Outputs ---
output "public_ip" {
  value = oci_core_instance.free_tier_instance.public_ip_address
}