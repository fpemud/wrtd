#!/usr/bin/python3
# -*- coding: utf-8; tab-width: 4; indent-tabs-mode: t -*-


class TemplateBridge:

    def get_name(self):
        assert False

    def get_prefix(self):
        # returns (ip, mask)
        assert False

    def get_bridge_id(self):
        assert False

    def add_source(self, source_id):
        assert False

    def remove_source(self, source_id):
        assert False

    def add_host(self, source_id, ip_data_dict):
        assert False

    def change_host(self, source_id, ip_data_dict):
        assert False

    def remove_host(self, source_id, ip_list):
        assert False

    def refresh_host(self, source_id, ip_data_dict):
        assert False


# plugin module name: plugins.manager_*
# config file: ${ETC}/manager-(PLUGIN_NAME).json
# manager unload is not supported, so manager_disappear() is not needed
class TemplatePluginManager:

    @property
    def init_after(self):
        # returns list<manager-name>
        assert False

    def init2(self, cfg, etcDir, tmpDir, varDir, pluginManagerData):
        assert False

    def dispose(self):
        assert False

    def get_router_info(self):
        assert False


class TemplatePluginManagerData:

    @property
    def etcDir(self):
        assert False

    @property
    def tmpDir(self):
        assert False

    @property
    def varDir(self):
        assert False

    @property
    def uuid(self):
        assert False

    @property
    def plugin_hub(self):
        assert False

    @property
    def prefix_pool(self):
        assert False

    @property
    def managet_caller(self):
        assert False

    @property
    def managers(self):
        # return dict<manager-name, manager-object>
        assert False


# template for json object
# FIXME: should support more protocols
class TemplateNetworkTrafficFacilityNameserver:

    @property
    def name(self):
        assert False

    @property
    def ntfac_type(self):
        return "nameserver"

    @property
    def target(self):
        """["hostname" or "hostname:port"]"""
        assert False

    @property
    def domain_list(self):
        assert False

    @property
    def domain_blacklist(self):
        assert False


# template for json object
class TemplateNetworkTrafficFacilityGateway:

    @property
    def name(self):
        assert False

    @property
    def ntfac_type(self):
        return "gateway"

    @property
    def target(self):
        """(next-hop,interface), invalid if both is None"""
        assert False

    @property
    def network_list(self):
        """["18.0.0.0/255.0.0.0","19.0.0.0/255.0.0.0"]"""
        assert False

    @property
    def network_blacklist(self):
        """["18.0.0.0/255.0.0.0","19.0.0.0/255.0.0.0"]"""
        assert False


# template for json object
class TemplateNetworkTrafficFacilityDefaultGateway:

    @property
    def name(self):
        assert False

    @property
    def ntfac_type(self):
        return "default-gateway"

    @property
    def target(self):
        """(next-hop,interface), invalid if both is None"""
        assert False

    @property
    def network_list(self):
        """["18.0.0.0/255.0.0.0","19.0.0.0/255.0.0.0"]"""
        assert False

    @property
    def network_blacklist(self):
        """["18.0.0.0/255.0.0.0","19.0.0.0/255.0.0.0"]"""
        assert False


# template for json object
class TemplateNetworkTrafficFacilityHttpProxy:

    """HTTP/HTTPS/FTP proxy"""

    @property
    def name(self):
        assert False

    @property
    def ntfac_type(self):
        return "http-proxy"

    @property
    def target(self):
        """(hostname,port)"""
        assert False

    @property
    def domain_list(self):
        assert False

    @property
    def domain_blacklist(self):
        assert False


# template for json object
class TemplatePublicIp:

    @property
    def ip(self):
        assert False

    @property
    def interface(self):
        assert False


# template for json object
class TemplateLanService:

    @property
    def protocol(self):
        assert False

    @property
    def port(self):
        assert False

    @property
    def txt_dict(self):
        assert False


# template for json object
class TemplateWanService:

    @property
    def firewall_allow_list(self):
        assert False
