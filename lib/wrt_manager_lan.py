#!/usr/bin/python3
# -*- coding: utf-8; tab-width: 4; indent-tabs-mode: t -*-

import os
import glob
import signal
import json
import socket
import subprocess
import logging
import ipaddress
import pyroute2
from gi.repository import Gio
from wrt_util import WrtUtil
from wrt_common import WrtCommon


class WrtLanManager:

    def __init__(self, param):
        self.param = param
        self.defaultBridge = None
        self.lifPluginList = []
        self.vpnsPluginList = []
        self.downstreamDict = dict()

        try:
            # create default bridge
            tmpdir = os.path.join(self.param.tmpDir, "bridge-default")
            os.mkdir(tmpdir)
            vardir = os.path.join(self.param.varDir, "bridge-default")
            WrtUtil.ensureDir(vardir)
            self.defaultBridge = _DefaultBridge(tmpdir, vardir)
            self.defaultBridge.init2("wrtd-br",
                                     self.param.prefixPool.usePrefix(),
                                     self.param.trafficManager.get_l2_nameserver_port(),
                                     lambda source_id, ip_data_dict: WrtCommon.callManagers(self.param, "on_client_add_or_change", source_id, ip_data_dict),
                                     lambda source_id, ip_list: WrtCommon.callManagers(self.param, "on_client_remove", source_id, ip_list))
            logging.info("Default bridge started.")

            # start all lan interface plugins
            for name in WrtCommon.getLanInterfacePluginList(self.param):
                for instanceName, cfgObj, tmpdir, vardir in self._getInstanceAndInfoFromEtcDir("lif", "lan-interface", name):
                    os.mkdir(tmpdir)
                    WrtUtil.ensureDir(vardir)

                    p = WrtCommon.getLanInterfacePlugin(self.param, name, instanceName)
                    p.init2(instanceName, cfgObj, tmpdir, vardir)
                    p.start()
                    self.lifPluginList.append(p)
                    logging.info("LAN interface plugin \"%s\" activated." % (p.full_name))

            # start all vpn server plugins
            for name in WrtCommon.getVpnServerPluginList(self.param):
                for instanceName, cfgObj, tmpdir, vardir in self._getInstanceAndInfoFromEtcDir("vpns", "vpn-server", name):
                    os.mkdir(tmpdir)
                    WrtUtil.ensureDir(vardir)

                    p = WrtCommon.getVpnServerPlugin(self.param, name, instanceName)
                    p.init2(instanceName,
                            cfgObj,
                            tmpdir,
                            vardir,
                            self.param.prefixPool.usePrefix(),
                            self.param.trafficManager.get_l2_nameserver_port(),
                            lambda source_id, ip_data_dict: WrtCommon.callManagers(self.param, "on_client_add_or_change", source_id, ip_data_dict),
                            lambda source_id, ip_list: WrtCommon.callManagers(self.param, "on_client_remove", source_id, ip_list),
                            lambda x: self._apiFirewallAllowFunc(p.full_name, x))
                    p.start()
                    self.vpnsPluginList.append(p)
                    logging.info("VPN server plugin \"%s\" activated." % (p.full_name))

            # get all bridges
            all_bridges = [self.defaultBridge] + [x.get_bridge() for x in self.vpnsPluginList]

            # send other-bridge-create event
            for bridge in all_bridges:
                for other_bridge in all_bridges:
                    if bridge == other_bridge:
                        continue
                    bridge.on_source_add(other_bridge.get_bridge_id())
        except BaseException:
            self._dispose()
            raise

    def dispose(self):
        self._dispose()
        logging.info("Terminated.")

    def on_client_add_or_change(self, source_id, ip_data_dict):
        assert len(ip_data_dict) > 0
        for bridge in [self.defaultBridge] + [x.get_bridge() for x in self.vpnsPluginList]:
            if source_id == bridge.get_bridge_id():
                continue
            bridge.on_host_add_or_change(source_id, ip_data_dict)

    def on_client_remove(self, source_id, ip_list):
        assert len(ip_list) > 0
        for bridge in [self.defaultBridge] + [x.get_bridge() for x in self.vpnsPluginList]:
            if source_id == bridge.get_bridge_id():
                continue
            bridge.on_host_remove(source_id, ip_list)

    def on_cascade_upstream_up(self, data):
        for bridge in [self.defaultBridge] + [x.get_bridge() for x in self.vpnsPluginList]:
            bridge.on_source_add("upstream-vpn")
        self._upstreamVpnHostRefresh()

    def on_cascade_upstream_down(self):
        for bridge in [self.defaultBridge] + [x.get_bridge() for x in self.vpnsPluginList]:
            bridge.on_source_remove("upstream-vpn")

    def on_cascade_upstream_router_add(self, data):
        self._upstreamVpnHostRefresh()

    def on_cascade_upstream_router_remove(self, data):
        self._upstreamVpnHostRefresh()

    def on_cascade_upstream_router_client_add_or_change(self, data):
        self._upstreamVpnHostRefresh()

    def on_cascade_upstream_router_client_remove(self, data):
        self._upstreamVpnHostRefresh()

    def on_cascade_downstream_up(self, peer_uuid, data):
        self.downstreamDict[peer_uuid] = []
        self.on_cascade_downstream_router_add(peer_uuid, data["router-list"])

    def on_cascade_downstream_down(self, peer_uuid):
        if len(self.downstreamDict[peer_uuid]) > 0:
            self.on_cascade_downstream_router_remove(peer_uuid, self.downstreamDict[peer_uuid])
        del self.downstreamDict[peer_uuid]

    def on_cascade_downstream_router_add(self, peer_uuid, data):
        for router_id in data.keys():
            self.downstreamDict[peer_uuid].append(router_id)
            for bridge in [self.defaultBridge] + [x.get_bridge() for x in self.vpnsPluginList]:
                bridge.on_source_add("downstream-" + router_id)
            self._downstreamVpnHostRefreshForRouter(peer_uuid, router_id)

    def on_cascade_downstream_router_remove(self, peer_uuid, data):
        for router_id in data:
            for bridge in [self.defaultBridge] + [x.get_bridge() for x in self.vpnsPluginList]:
                bridge.on_source_remove("downstream-" + router_id)

    def on_cascade_downstream_router_client_add_or_change(self, peer_uuid, data):
        for router_id in data.keys():
            self._downstreamVpnHostRefreshForRouter(peer_uuid, router_id)

    def on_cascade_downstream_router_client_remove(self, peer_uuid, data):
        for router_id in data.keys():
            self._downstreamVpnHostRefreshForRouter(peer_uuid, router_id)

    def _apiFirewallAllowFunc(self, owner, rule):
        class _Stub:
            pass
        data = _Stub
        data.firewall_allow = [rule]
        self.param.trafficManager.set_data(owner, data)

    def _upstreamVpnHostRefresh(self):
        # we need to differentiate upstream router and other client, so we do refresh instead of add/change/remove
        ipDataDict = dict()

        # add upstream routers into ipDataDict
        upstreamRouterLocalIpList = []
        if self.param.cascadeManager.hasValidApiClient():
            curUpstreamId = self.param.cascadeManager.apiClient.get_peer_uuid()
            curUpstreamIp = self.param.cascadeManager.apiClient.get_peer_ip()
            curUpstreamLocalIp = self.param.wanManager.vpnPlugin.get_local_ip()
            while True:
                data = self.param.cascadeManager.apiClient.get_upstream_router_info()[curUpstreamId]

                ipDataDict[curUpstreamIp] = dict()
                if "hostname" in data:
                    ipDataDict[curUpstreamIp]["hostname"] = data["hostname"]
                upstreamRouterLocalIpList.append(curUpstreamLocalIp)

                if "parent" not in data:
                    break
                curUpstreamId = data["parent"]
                curUpstreamIp = data["cascade-vpn"]["remote-ip"]
                curUpstreamLocalIp = data["cascade-vpn"]["local-ip"]

        # add all clients into ipDataDict
        for router in self.param.cascadeManager.apiClient.get_upstream_router_info().values():
            if "client-list" in router:
                for ip, data in router["client-list"].items():
                    if ip in upstreamRouterLocalIpList:
                        continue
                    if "nat-ip" in data:
                        ip = data["nat-ip"]
                        data = data.copy()
                        del data["nat-ip"]
                    ipDataDict[ip] = data

        # refresh to all bridges
        for bridge in [self.defaultBridge] + [x.get_bridge() for x in self.vpnsPluginList]:
            bridge.on_host_refresh("upstream-vpn", ipDataDict)

    def _downstreamVpnHostRefreshForRouter(self, peer_uuid, router_id):
        # we don't want to record "nat-ip" information, so we do refresh instead of add/change/remove
        ipDataDict = dict()

        # get router data
        routerData = None
        for sproc in self.param.cascadeManager.getAllValidApiServerProcessors():
            if sproc.get_peer_uuid() == peer_uuid:
                for id2, data2 in sproc.get_downstream_router_info().items():
                    if id2 == router_id:
                        routerData = data2
                        break
                if routerData is not None:
                    break
        assert routerData is not None

        # add all clients into ipDataDict
        for ip, data in routerData["client-list"].items():
            if "nat-ip" in data:
                ip = data["nat-ip"]
                data = data.copy()
                del data["nat-ip"]
            ipDataDict[ip] = data

        # refresh to all bridges
        for bridge in [self.defaultBridge] + [x.get_bridge() for x in self.vpnsPluginList]:
            bridge.on_host_refresh("downstream-" + router_id, ipDataDict)

    def _getInstanceAndInfoFromEtcDir(self, pluginPrefix, cfgfilePrefix, name):
        # Returns (instanceName, cfgobj, tmpdir, vardir)

        ret = []
        for fn in glob.glob(os.path.join(self.param.etcDir, "%s-%s*.json" % (cfgfilePrefix, name))):
            bn = os.path.basename(fn)

            instanceName = bn[len("%s-%s" % (cfgfilePrefix, name)):len(".json") * -1]
            if instanceName != "":
                instanceName = instanceName.lstrip("-")

            if instanceName != "":
                fullName = "%s-%s" % (name, instanceName)
            else:
                fullName = name

            if os.path.getsize(fn) > 0:
                with open(fn, "r") as f:
                    cfgObj = json.load(f)
            else:
                cfgObj = dict()

            tmpdir = os.path.join(self.param.tmpDir, "%s-%s" % (pluginPrefix, fullName))
            vardir = os.path.join(self.param.varDir, "%s-%s" % (pluginPrefix, fullName))

            ret.append((instanceName, cfgObj, tmpdir, vardir))

        if len(ret) == 0:
            instanceName = ""
            fullName = name
            cfgObj = dict()
            tmpdir = os.path.join(self.param.tmpDir, "%s-%s" % (pluginPrefix, fullName))
            vardir = os.path.join(self.param.varDir, "%s-%s" % (pluginPrefix, fullName))
            ret.append((instanceName, cfgObj, tmpdir, vardir))

        return ret

    def _dispose(self):
        for p in self.vpnsPluginList:
            p.stop()
            logging.info("VPN server plugin \"%s\" deactivated." % (p.full_name))
        self.vpnsPluginList = []

        for p in self.lifPluginList:
            p.stop()
            logging.info("LAN interface plugin \"%s\" deactivated." % (p.full_name))
        self.lifPluginList = []

        if self.defaultBridge is not None:
            self.defaultBridge.dispose()
            self.defaultBridge = None
            logging.info("Default bridge destroyed.")


class _DefaultBridge:

    def __init__(self, tmpDir, varDir):
        self.tmpDir = tmpDir
        self.varDir = varDir
        self.l2DnsPort = None
        self.clientAddOrChangeFunc = None
        self.clientRemoveFunc = None

        self.brname = None
        self.brnetwork = None
        self.dhcpRange = None
        self.subhostIpRange = None

        self.myhostnameFile = os.path.join(self.tmpDir, "dnsmasq.myhostname")
        self.hostsDir = os.path.join(self.tmpDir, "hosts.d")
        self.leasesFile = os.path.join(self.tmpDir, "dnsmasq.leases")
        self.pidFile = os.path.join(self.tmpDir, "dnsmasq.pid")
        self.dnsmasqProc = None
        self.leaseMonitor = None
        self.lastScanRecord = None

    def init2(self, brname, prefix, l2dns_port, client_add_or_change_func, client_remove_func):
        assert prefix[1] == "255.255.255.0"

        self.brname = brname
        self.brnetwork = ipaddress.IPv4Network(prefix[0] + "/" + prefix[1])

        self.brip = ipaddress.IPv4Address(prefix[0]) + 1
        self.dhcpRange = (self.brip + 1, self.brip + 49)

        self.l2DnsPort = l2dns_port
        self.clientAddOrChangeFunc = client_add_or_change_func
        self.clientRemoveFunc = client_remove_func

        # create bridge interface
        with pyroute2.IPRoute() as ip:
            ip.link("add", kind="bridge", ifname=self.brname)
            idx = ip.link_lookup(ifname=self.brname)[0]
            ip.link("set", index=idx, state="up")
            ip.addr("add", index=idx, address=str(self.brip), mask=self.brnetwork.prefixlen, broadcast=str(self.brnetwork.broadcast_address))

        # start dnsmasq
        self._runDnsmasq()
        with open("/etc/resolv.conf", "w") as f:
            f.write("# Generated by wrtd\n")
            f.write("nameserver 127.0.0.1\n")

    def dispose(self):
        with open("/etc/resolv.conf", "w") as f:
            f.write("")
        self._stopDnsmasq()
        with pyroute2.IPRoute() as ip:
            idx = ip.link_lookup(ifname=self.brname)[0]
            ip.link("set", index=idx, state="down")
            ip.link("del", index=idx)

    def get_name(self):
        return self.brname

    def get_bridge_id(self):
        return "bridge-%s" % (self.brip)

    def get_prefix(self):
        return (str(self.brnetwork.network_address), str(self.brnetwork.netmask))

    def get_subhost_ip_range(self):
        subhostIpRange = []
        i = 51
        while i + 49 < 255:
            subhostIpRange.append((str(self.brip + i), str(self.brip + i + 49)))
            i += 50
        return subhostIpRange

    def on_source_add(self, source_id):
        with open(os.path.join(self.hostsDir, source_id), "w") as f:
            f.write("")

    def on_source_remove(self, source_id):
        os.unlink(os.path.join(self.hostsDir, source_id))

    def on_host_add_or_change(self, source_id, ip_data_dict):
        fn = os.path.join(self.hostsDir, source_id)
        itemDict = WrtUtil.dnsmasqHostFileToOrderedDict(fn)
        bChanged = False

        for ip, data in ip_data_dict.items():
            if ip in itemDict:
                if "hostname" in data:
                    if itemDict[ip] != data["hostname"]:
                        itemDict[ip] = data["hostname"]
                        bChanged = True
                else:
                    del itemDict[ip]
                    bChanged = True
            else:
                if "hostname" in data:
                    itemDict[ip] = data["hostname"]
                    bChanged = True

        if bChanged:
            WrtUtil.dictToDnsmasqHostFile(itemDict, fn)
            self.dnsmasqProc.send_signal(signal.SIGHUP)

    def on_host_remove(self, source_id, ip_list):
        fn = os.path.join(self.hostsDir, source_id)
        itemDict = WrtUtil.dnsmasqHostFileToOrderedDict(fn)
        bChanged = False

        for ip in ip_list:
            if ip in itemDict:
                del itemDict[ip]
                bChanged = True

        if bChanged:
            WrtUtil.dictToDnsmasqHostFile(itemDict, fn)
            self.dnsmasqProc.send_signal(signal.SIGHUP)

    def on_host_refresh(self, source_id, ip_data_dict):
        fn = os.path.join(self.hostsDir, source_id)
        itemDict = WrtUtil.dnsmasqHostFileToDict(fn)

        itemDict2 = dict()
        for ip, data in ip_data_dict.items():
            if "hostname" in data:
                itemDict[ip] = data["hostname"]

        if itemDict != itemDict2:
            WrtUtil.dictToDnsmasqHostFile(itemDict2, fn)
            self.dnsmasqProc.send_signal(signal.SIGHUP)

    def _runDnsmasq(self):
        # myhostname file
        with open(self.myhostnameFile, "w") as f:
            f.write("%s %s\n" % (self.brip, socket.gethostname()))

        # make hosts directory
        os.mkdir(self.hostsDir)

        # create empty leases file
        with open(self.leasesFile, "w") as f:
            f.write("")

        # generate dnsmasq config file
        buf = ""
        buf += "strict-order\n"
        buf += "bind-interfaces\n"                                       # don't listen on 0.0.0.0
        buf += "interface=lo,%s\n" % (self.brname)
        buf += "user=root\n"
        buf += "group=root\n"
        buf += "\n"
        buf += "dhcp-authoritative\n"
        buf += "dhcp-range=%s,%s,%s,360\n" % (self.dhcpRange[0], self.dhcpRange[1], self.brnetwork.netmask)
        buf += "dhcp-option=option:T1,180\n"                             # strange that dnsmasq's T1=165s, change to 180s which complies to RFC
        buf += "dhcp-leasefile=%s\n" % (self.leasesFile)
        buf += "\n"
        buf += "domain-needed\n"
        buf += "bogus-priv\n"
        buf += "no-hosts\n"
        buf += "server=127.0.0.1#%d\n" % (self.l2DnsPort)
        buf += "addn-hosts=%s\n" % (self.hostsDir)                       # "hostsdir=" only adds record, no deletion, so not usable
        buf += "addn-hosts=%s\n" % (self.myhostnameFile)                 # we use addn-hosts which has no inotify, and we send SIGHUP to dnsmasq when host file changes
        buf += "\n"
        cfgf = os.path.join(self.tmpDir, "dnsmasq.conf")
        with open(cfgf, "w") as f:
            f.write(buf)

        # run dnsmasq process
        cmd = "/usr/sbin/dnsmasq"
        cmd += " --keep-in-foreground"
        cmd += " --conf-file=\"%s\"" % (cfgf)
        cmd += " --pid-file=%s" % (self.pidFile)
        self.dnsmasqProc = subprocess.Popen(cmd, shell=True, universal_newlines=True)

        # monitor dnsmasq lease file
        self.leaseMonitor = Gio.File.new_for_path(self.leasesFile).monitor(0, None)
        self.leaseMonitor.connect("changed", self._dnsmasqLeaseChanged)
        self.lastScanRecord = []

    def _stopDnsmasq(self):
        self.lastScanRecord = None
        if self.leaseMonitor is not None:
            self.leaseMonitor.cancel()
            self.leaseMonitor = None
        if self.dnsmasqProc is not None:
            self.dnsmasqProc.terminate()
            self.dnsmasqProc.wait()
            self.dnsmasqProc = None
        WrtUtil.forceDelete(self.pidFile)
        WrtUtil.forceDelete(self.leasesFile)
        WrtUtil.forceDelete(self.hostsDir)
        WrtUtil.forceDelete(self.myhostnameFile)

    def _dnsmasqLeaseChanged(self, monitor, file, other_file, event_type):
        if event_type != Gio.FileMonitorEvent.CHANGED:
            return

        try:
            newLeaseList = WrtUtil.readDnsmasqLeaseFile(self.leasesFile)

            addList = []
            changeList = []
            removeList = []
            for item in newLeaseList:
                item2 = self.___dnsmasqLeaseChangedFind(item, self.lastScanRecord)
                if item2 is not None:
                    if item[1] != item2[1] or item[3] != item2[3]:      # mac or hostname change
                        changeList.append(item)
                else:
                    addList.append(item)
            for item in self.lastScanRecord:
                if self.___dnsmasqLeaseChangedFind(item, newLeaseList) is None:
                    removeList.append(item)

            if len(addList) > 0 or len(changeList) > 0:
                ipDataDict = dict()
                for expiryTime, mac, ip, hostname, clientId in addList:
                    self.__dnsmasqLeaseChangedAddToIpDataDict(ipDataDict, ip, mac, hostname)
                    if hostname != "":
                        self.pObj.logger.info("Client %s(IP:%s, MAC:%s) appeared." % (hostname, ip, mac))
                    else:
                        self.pObj.logger.info("Client %s(%s) appeared." % (ip, mac))
                for expiryTime, mac, ip, hostname, clientId in changeList:
                    self.__dnsmasqLeaseChangedAddToIpDataDict(ipDataDict, ip, mac, hostname)
                    # log is not needed for client change
                self.clientAddOrChangeFunc(self.get_bridge_id(), ipDataDict)

            if len(removeList) > 0:
                ipList = [x[2] for x in removeList]
                self.clientRemoveFunc(self.get_bridge_id(), ipList)
                for expiryTime, mac, ip, hostname, clientId in removeList:
                    if hostname != "":
                        self.pObj.logger.info("Client %s(IP:%s, MAC:%s) disappeared." % (hostname, ip, mac))
                    else:
                        self.pObj.logger.info("Client %s(%s) disappeared." % (ip, mac))

            self.lastScanRecord = newLeaseList
        except Exception as e:
            self.pObj.logger.error("Lease scan failed", exc_info=True)      # fixme

    def ___dnsmasqLeaseChangedFind(self, item, leaseList):
        for item2 in leaseList:
            if item2[2] == item[2]:     # compare by ip
                return item2
        return None

    def __dnsmasqLeaseChangedAddToIpDataDict(self, ipDataDict, ip, mac, hostname):
        ipDataDict[ip] = dict()
        ipDataDict[ip]["wakeup-mac"] = mac
        if hostname != "":
            ipDataDict[ip]["hostname"] = hostname
