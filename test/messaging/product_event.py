#! /usr/bin/env python
#
# This Driver script simulates a product create event on the bus
# similar to what's expected of candlepin
# 
# Copyright (c) 2010 Red Hat, Inc.
#
# This software is licensed to you under the GNU General Public License,
# version 2 (GPLv2). There is NO WARRANTY for this software, express or
# implied, including the implied warranties of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. You should have received a copy of GPLv2
# along with this software; if not, see
# http://www.gnu.org/licenses/old-licenses/gpl-2.0.txt.
#
# Red Hat trademarks are not licensed under GPLv2. No permission is
# granted to use or replicate Red Hat trademarks that are incorporated
# in this software or its documentation.
#

import sys
sys.path.append('../../')

from pulp.messaging.producer import EventProducer
from pulp.server.event.dispatcher import EventDispatcher
#from logging import INFO, basicConfig
from optparse import Option, OptionParser

#basicConfig(filename='/tmp/messaging.log', level=INFO)
# change these paths appropriately to suit your env
CERT_FILE="/certs/nimbus_cloude_debug.crt"
CERT_KEY="/certs/nimbus_cloude_debug.key"
CA_CERT="/certs/cdn.redhat.com-chain.crt"

class ProductDriver:
        
    def create(self):
        #ed = EventDispatcher()
        #ed.start()
        p = EventProducer()
        content_set = [{
            'content_set_label' : "rhel-server" ,
            'content_rel_url' : "/content/dist/rhel/server/$releasever/$basearch/os"},]
        cert_data = {'ca' : open(CA_CERT, "rb").read(),
                     'cert' : open(CERT_FILE, "rb").read(),
                     'key' : open(CERT_KEY, 'rb').read()}
        d = dict(
                 id='1',
                 name = 'rhel-server',
                 content_sets=content_set,
                 ca_cert = open(CA_CERT, "rb").read(),
                 entitlement_cert =  open(CERT_FILE, "rb").read(),
                 cert_public_key  = open(CERT_KEY, 'rb').read()
                 )
        p.send('product.created', d)
        #ed.stop()
        
    def update(self):
        p = EventProducer()
        content_set = [{
            'content_set_label' : "rhel-server" ,
            'content_rel_url' : "/content/dist/rhel/server/$releasever/$basearch/os"},]
        cert_data = {'ca' : open(CA_CERT, "rb").read(),
                     'cert' : open(CERT_FILE, "rb").read(),
                     'key' : open(CERT_KEY, 'rb').read()}
        d = dict(
                 id='1',
                 name = 'rhel-server',
                 content_sets=content_set,
                 ca_cert = open(CA_CERT, "rb").read(),
                 entitlement_cert =  open(CERT_FILE, "rb").read(),
                 cert_public_key  = open(CERT_KEY, 'rb').read()
                 )
        p.send('product.updated', d)
    
    def delete(self):
        p = EventProducer()
        d = dict(
                 id='1',
                 name = 'rhel-server',
                 owner = 'admin',
                 )
        p.send('product.deleted', d)
        
def main():
    options_table = [
    Option("--create", action="store_true",
        help="Raise a product create event on qpid bus"),
    Option("--update", action="store_true",
        help="Raise a product update event on qpid bus"),
    Option("--delete", action="store_true",
        help="Raise a product delete event on qpid bus"),
    ]
    parser = OptionParser(option_list=options_table)
    (options, args) = parser.parse_args()
    pd = ProductDriver()
    if options.create:
        pd.create()
        print("Raised a product.created event on qpid bus")
    if options.update:
        pd.update()
        print("Raised a product.updated event on qpid bus")
    if options.delete:
        pd.delete()
        print("Raised a product.deleted event on qpid bus")
        


if __name__ == '__main__':
    main()
