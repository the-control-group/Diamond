# coding=utf-8

import diamond.collector
import urllib2
import subprocess
import json
import time
import psutil


class Pm2Collector(diamond.collector.Collector):

    def get_default_config_help(self):
        config_help = super(Pm2Collector, self).get_default_config_help()
        config_help['use_api'] = "Whether to use pm2's API to collect metrics."
        config_help['api_host'] = 'The host from which to collect pm2 metrics. Only relevant if use_api = True.'
        config_help['api_port'] = 'The port on which the API is listening. Only relevant if use_api = True.'
        return config_help

    def get_default_config(self):
        config = super(Pm2Collector, self).get_default_config()
        config['use_api'] = 'True'
        config['api_host'] = 'localhost'
        config['api_port'] = 9615
        return config

    def get_data_via_api(self):
        try:
            port = int(self.config['api_port'])
        except ValueError, e:
            self.log.error("Invalid port number '%s' specified in configuration." % self.config['api_port'])
            return None

        try:
    	    response = urllib2.urlopen('http://%s:%i' % (self.config['api_host'], port), timeout=5)
    	except urllib2.URLError, e:
            self.log.error("Could not collect metrics via API on %s:%i" % (self.config['api_host'], port))
            return None
    	
        try:
            result = json.load(response)
        except ValueError, e:
            self.log.error("Could not parse response from http://%s:%i as JSON" % (self.config['api_host'], port))
            return None

        self.log.debug('Successfully collected data via API (http://%s:%i)' % (self.config['api_host'], port))
        return result['processes']

    def get_data_via_cli(self):
        pm2_running = False
        for proc in psutil.process_iter():
            if 'pm2' in proc.name():
                pm2_running = True
                break

        # only invoke 'pm2 jlist' if pm2 is already running (e.g. if it's not been pm2 kill'ed by someone)
        # if it's been killed previously and we call 'pm2 list' in here, it'll start pm2 back up!
        if pm2_running:
            try:
    	       output = subprocess.check_output(['pm2','jlist'])
            except OSError, e:
                self.log.error("Could not execute command 'pm2 jlist'. Is pm2 installed?")
                return None

            try:
                result = json.loads(output)
            except ValueError, e:
                self.log.error("Could not parse 'pm2 jlist' output as JSON")
                return None

            self.log.debug('Successfully collected data via CLI (pm2 jlist)')
            return result
        else:
            self.log.debug('Skipping pm2 metrics collection since pm2 does not seem to be running!')
            return None

    def collect(self):
    	processes = None

        if self.config['use_api'].lower() == 'true':
            processes = self.get_data_via_api()

        # fall back to CLI data collection if API fails
        if processes is None:
            processes = self.get_data_via_cli()

        if processes is None:
            self.log.error('Failed to collect pm2 metrics.')
            return

        for proc in processes:
            self.publish("%s.%s" % (proc['name'], 'memory'), proc['monit']['memory'] / 1000. / 1000., metric_type='GAUGE', precision=2)

            # if proc is under heavy load, sometimes the CPU metric can be None
            if proc['monit']['cpu'] is not None:
                self.publish("%s.%s" % (proc['name'], 'cpu'), proc['monit']['cpu'], metric_type='GAUGE')

            # it seems pm_uptime reports the same value as created_at. we must calculate uptime for ourselves.
            uptime = int(time.time()) - int(proc['pm2_env']['pm_uptime'] / 1000.)
            self.publish("%s.%s" % (proc['name'], 'uptime'), uptime)

            # apparently, restart_time actually means *number of restarts*
            # It's used as the value for the 'Restarted' column in 'pm2 list' output
            self.publish("%s.%s" % (proc['name'], 'restarts'), proc['pm2_env']['restart_time'])