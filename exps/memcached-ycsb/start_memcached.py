#!/usr/bin/python

import argparse
import glob
import os
import platform
import subprocess
import sys
import yaml
from time import sleep

sys.path.insert(0, os.path.abspath('..'))
from loom_exp_common import *

if 'LOOM_HOME' in os.environ:
    LOOM_HOME = os.environ['LOOM_HOME']
else:
    LOOM_HOME = '/proj/opennf-PG0/exp/loomtest/datastore/git/loom-code/'

DRIVER_DIR = LOOM_HOME + '/code/ixgbe-5.0.4/'

QMODEL_SQ = 'sq'
QMODEL_MQ = 'mq'
QMODEL_BESS = 'bess'

MEMCACHED_CONFIG_DEFAULTS = {
    #'qmodel': QMODEL_SQ,
    'qmodel': QMODEL_BESS,
    'rate_limit': 2e9,
    'iface': 'eno2',
    'iface_addr': '0000:81:00.1',
    'max_mem': (16 * 1024),
    'threads': 16,

    'bess_conf': 'memcached_rl.bess',

    #XXX: Not really used anymore
    'servers': [
        {'cpu': 0, 'port': 11212},
        #{'cpu': 4, 'port': 11214},
    ],
}

class ServerConfig(object):
    def __init__(self, *initial_data, **kwargs):
        for dictionary in initial_data:
            for key in dictionary:
                setattr(self, key, dictionary[key])
        for key in kwargs:
            setattr(self, key, kwargs[key])
    def dump(self):
        return self.__dict__.copy()

class MemcachedConfig(object):
    def __init__(self, *initial_data, **kwargs):
        for key in MEMCACHED_CONFIG_DEFAULTS:
            setattr(self, key, MEMCACHED_CONFIG_DEFAULTS[key])
        for dictionary in initial_data:
            for key in dictionary:
                if not hasattr(self, key):
                    print 'WARNING! Unexpected attr: %s' % key
                setattr(self, key, dictionary[key])
        for key in kwargs:
            if not hasattr(self, key):
                print 'WARNING! Unexpected attr: %s' % key
            setattr(self, key, kwargs[key])
        # Parse the server config
        self.servers = [ServerConfig(s) for s in self.servers]
    def dump(self):
        d = self.__dict__.copy()
        d['servers'] = d['servers'].dump()
        return d

def memcached_config_nic_driver(config):
    # Get the current IP
    get_ip_cmd='/sbin/ifconfig %s | grep \'inet addr:\' | cut -d: -f2 | awk \'{ print $1}\'' % config.iface
    ip = subprocess.check_output(get_ip_cmd, shell=True)
    ip = ip.strip()

    # Remove the driver
    rm_cmd = 'sudo rmmod ixgbeloom'
    os.system(rm_cmd) # Ignore everything

    # Craft the args for the driver
    ixgbe = DRIVER_DIR + '/src/ixgbeloom.ko'
    rss_str = '' if config.qmodel == QMODEL_MQ else 'RSS=1,1'
    drv_cmd = 'sudo insmod %s %s' % (ixgbe, rss_str)

    # Add in the new driver
    subprocess.check_call(drv_cmd, shell=True)

    # Unbind the module from ixgbe always even if not present and bind to ixgbetitan
    cmd = "sudo /bin/su -c \"echo -n '0000:81:00.1' > /sys/bus/pci/drivers/ixgbe/unbind\""
    os.system(cmd)
    cmd = "sudo /bin/su -c \"echo -n '0000:81:00.1' > /sys/bus/pci/drivers/ixgbeloom/bind\""
    os.system(cmd)

    # Assign the IP
    ip_cmd = 'sudo ifconfig %s %s netmask 255.255.255.0' % (config.iface, ip)
    subprocess.check_call(ip_cmd, shell=True)

def get_txqs(args):
    txqs = glob.glob('/sys/class/net/%s/queues/tx-*' % args.iface)
    return txqs

def get_rxqs(config):
    rxqs = glob.glob('/sys/class/net/%s/queues/rx-*' % config.iface)
    return rxqs 

def memcached_configure_rfs(config):
    rxqs = get_rxqs(config)
    if len(rxqs) == 0:
        rxqs = range(64)
    entries = 65536
    entries_per_rxq = entries / len(rxqs)
    cmd = 'echo %d | sudo tee /proc/sys/net/core/rps_sock_flow_entries > /dev/null' % \
        entries
    subprocess.check_call(cmd, shell=True)
    for rxq in rxqs:
        cmd = 'echo %d | sudo tee /%s/rps_flow_cnt > /dev/null' % (entries_per_rxq, rxq)
        subprocess.check_call(cmd, shell=True)

def memcached_config_xps(config):
    if config.qmodel == QMODEL_MQ:
        # Use the Intel script to configure XPS
        subprocess.call('sudo killall irqbalance', shell=True)
        xps_script = DRIVER_DIR + '/scripts/set_irq_affinity'
        subprocess.call('sudo %s -x all %s' % (xps_script, config.iface),
            shell=True)

        # Also configure RFS
        memcached_configure_rfs(config)
    else:
        #Note: maybe not necessary.  But it shouldn't hurt to restart irqbalance
        subprocess.call('sudo service irqbalance restart', shell=True)

def memcached_config_qdisc(config):
    qcnt = len(get_txqs(config))
    for i in xrange(1, qcnt + 1):
        # Configure a tbf Qdisc per txq
        rate_mbit = int(config.rate_limit / 1e6)
        tc_cmd = 'sudo tc qdisc add dev %s parent :%x tbf rate %dmbit ' \
            'burst 1000kb limit 10000000' % \
            (config.iface, i, rate_mbit)
        subprocess.check_call(tc_cmd, shell=True)

        #XXX: This code doesn't work.  Also, htb is not necessary here.  tbf
        # should work well enough instead.
        # Default [x] means that unclassified traffic is sent to classid [x]
        #tc_cmd = 'sudo tc qdisc add dev %s parent :%x handle %d0: htb default 12 r2q 1' % \
        #    (config.iface, i, i)
        #subprocess.check_call(tc_cmd, shell=True)
        #tc_cmd = 'sudo tc class add dev %s parent %d0: classid %d0:12 htb rate 1000mbps' % \
        #    (config.iface, i, i)
        #subprocess.check_call(tc_cmd, shell=True)

def memcached_config_server(config):
    # Configure the number of NIC queues
    memcached_config_nic_driver(config)

    #TODO: Configure XPS
    memcached_config_xps(config)

    #TODO: Configure Qdisc/TC
    memcached_config_qdisc(config)

def memcached_config_bess(config):
    loom_config_bess(config)

    # Also configure RFS
    iface_save = config.iface
    config.iface = 'loom'
    memcached_configure_rfs(config)
    config.iface = iface_save

def memcached_start_servers(config):
    #XXX: "-L" enables hugepage support.  This currently didn't work for me.
    cmd_tmpl = '/usr/bin/memcached -m %(max_mem)d -p %(port)s -u memcache -t %(threads)s -R 1000 -d -c 4096'

    procs = []
    for server_conf in config.servers:
        cmd = cmd_tmpl % {'max_mem': config.max_mem, 'port': server_conf.port,
            'threads': config.threads}

        #XXX: Don't pin cores for now
        #taskset_tmpl = 'sudo taskset -c %(cpu)s %(cmd)s'
        #taskset_cmd = taskset_tmpl % {'cpu': server_conf.cpu, 'cmd': cmd}
        taskset_cmd = 'sudo ' + cmd

        proc = subprocess.Popen(taskset_cmd, shell=True,
            stderr=subprocess.STDOUT, stdout=subprocess.PIPE)
        procs.append(proc)
    return procs

def memcached_kill_servers(config):
    #XXX: WARNING: This will kill all memcached processes running
    kill_cmd = 'sudo killall memcached'
    subprocess.call(kill_cmd, shell=True)

def main():
    # Parse arguments
    parser = argparse.ArgumentParser(description='Configure the server and '
        'start memcached for the rate-limiting and fairness experiment')
    parser.add_argument('--config', help='An alternate configuration file. '
        'The configuration format is unsurprisingly not documented.')
    parser.add_argument('--rate-limit', help='Override the rate-limit in '
        'the config.', type=float)
    args = parser.parse_args()

    # Get the config
    if args.config:
        with open(args.config) as configf:
            user_config = yaml.load(configf)
        config = MemcachedConfig(user_config)
    else:
        config = MemcachedConfig()

    # Overwrite the rate-limit if requested.
    if args.rate_limit:
        config.rate_limit = args.rate_limit

    # Kill all old servers
    memcached_kill_servers(config)
    sleep(0.1)

    # Configure the server
    if config.qmodel == QMODEL_BESS:
        memcached_config_bess(config)
    else:
        memcached_config_server(config)

    # Start the memcached servers
    procs = memcached_start_servers(config)

    #XXX: DEBUG
    for proc in procs:
        print proc.stdout.read()

if __name__ == '__main__':
    main()
