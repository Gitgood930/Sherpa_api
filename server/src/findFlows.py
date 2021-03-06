#!/usr/bin/env python3

### findFlows.py
###     release date: March 20, 2020
###     author: David Nicol
###     contact: dmnicol@illinois.edu
###
###
### Read the topology, rules, and ip information for a network and then
### find all 'interesting' flows, defined as those with at least as many hops 
### as command-line parameter '-mh' (minimum hops)
###

import pdb
import argparse
import sys
import os
import io
import shutil
import json
import copy

from .makeEvals      import mineLinkDefs
from collections    import defaultdict
from .utils.network  import buildNetwork
from .utils.flow     import Flow, cleanUp
from .utils.ipn      import IPValues, inIPFormat
from .utils.rule     import RuleNewlySeen, MatchNewlySeen, ActionNewlySeen 
from .utils.linkstate  import buildLinkState, saveLinkState

### global variables
topo_file  = ''
rules_file = ''
flows_file = ''
output_file = ''
session_file = ''
switch_file = ''

flowsDict  = {}
linkState = {}
failedToRoute = []
minimum_hops = 0
cmd_str      = ''

def resetGlobalVariables():
    global topo_file, rules_file, flows_file, output_file, session_file, switch_file
    global flowsDict, linkState, failedToRoute, minimum_hops, cmd_str

    topo_file  = ''
    rules_file = ''
    flows_file = ''
    output_file = ''
    session_file = ''
    switch_file = ''

    flowsDict  = {}
    linkState = {}
    failedToRoute = []
    minimum_hops = 0
    cmd_str      = ''

    MatchNewlySeen = set()
    RuleNewlySeen = set()
    ActionNewlySeen = set()

def readTopoFile( topo_file ):
    try:
        with open(topo_file,'r') as tf:
            tstr  = tf.read()
            tdict = json.loads(tstr)

    except:
        print('Problem reading topology json file', file=sys.stderr )
        raise Exception

    return tdict['one_hop_neighbor_nodes']

def readRulesFile( rules_file ):
    try:
        with open(rules_file,'r') as rf:
            rstr = rf.read()
            rdict = json.loads(rstr)
    except:
        print('Problem reading rules json file', file=sys.stderr )
        raise Exception

    return rdict

def readIPFile( ip_file ):
    try:
        with open(ip_file,'r') as ipf:
            ipstr = ipf.read()
            nodeIPs = json.loads(ipstr)
    except:
        print('Problem reading IP json file', file=sys.stderr )
        raise Exception

    return nodeIPs


### extract from the rules combinations of ip_dscp and nw_dst that commonly appear
### in the match dictionary
###   For each switch construct a list of unique pairs, with a description of these
###
def mineRules( switches ):

    ### for each switch create templates of ip_dscp and nw_dst values that 
    ### pass rules, and a description of presentation to neighboring switches
    ###
    hdr_template = {}

    for switchId, switch in switches.items():
        hdr_template[ switchId ] = []
        outputPorts = defaultdict(list)
        template_set = set()

        for rule in switch.tables[0]:
            if 'ip_dscp' in rule.match and 'nw_dst' in rule.match:
                ip_dscp = rule.match['ip_dscp']
                nw_dst  = rule.match['nw_dst']

                if 'in_port' in rule.match:
                    in_port = rule.match['in_port']
                else:
                    in_port = '*'
 
                template_set.add( (in_port, ip_dscp, nw_dst) )      

        hdr_template[ switchId ] = sorted( list(template_set) )
        
    return hdr_template 
    

### a link between switches is seen by one switch as a particular port id, and by the other switch
### by a potentially different port id.  This function creates a nested dictionary structure which,
### given a switch id and a port number as viewed from that switch is mapped to a tuple describing the
### the switch at the other end and the port id of the link as viewed by that switch.
###
def makeNeighborMap(switches):

    neighborMap = defaultdict(dict)

    for switchId, switch in switches.items():

        for portId, nbrId in switch.nbrs.items():
            nbr = switches[ nbrId ]

            for peerPortId, peerSwitchId in nbr.nbrs.items():
                if peerSwitchId == switchId:
                    neighborMap[ switchId ][ portId ] = ( nbrId, peerPortId )
            
    return neighborMap

### from each switch launch flows to neighbors with ip_dscp and nw_dst characteristics from
### the 's 'match' field of the switch's rules.   As we don't yet know how traffic is assumed
### to enter the system, this approach figures it drops out of heaven and must match one of the rules.
### As the packet goes forward it doesn't matter which in_port on the source switch was involved, if any.
###   The heavy lifting (including routing etc.) is done at the switch level, calling switch method
### discoverFlows.

def findViableFlows( switches, neighborMap, mh = 0):
    results = {}

    flowCount = defaultdict(int)
    flow_hdrs = mineRules( switches )

    ### visit every switch
    for switchId in flow_hdrs:
        switch = switches[ switchId ]

        ### visit every
        for (in_port, ip_dscp, nw_dst) in flow_hdrs[ switchId ]:

            ### make the in_port a wildcard for the purposes of matching the flow's entrace
            flowState = {'nsrc':switchId,'ndst':None,'ip_dscp':ip_dscp,'nw_dst':nw_dst,'dl_type':2048,\
                'nw_ttl':24, 'in_port':in_port, 'ingress_port':in_port }

            flow = Flow( None, flowState )
            ### ask the switch to launch a search with the identified flow, convey the minimum hop count and
            ### whether to exclude complex rules or not
            ###
            discovered = switch.discoverFlows( flow, in_port, switches, neighborMap)
           
            for dflow in discovered:
                
                ### if path not long enough for interest, ignore it
                ###
                if len(dflow.visited) < mh:
                    continue

                ### the sdn simulator uses a specific form for 
                ### naming flows.  Create the name, and add the vars structure
                ### of the flow to the results dictionary indexed by flow name.
                ###
                base_name = switchId+'-'+dflow.vars['ndst']
                pnumber = flowCount[ base_name ]
                flowCount[ base_name ] += 1
                dname   = base_name+'-'+str(pnumber)

                ### add visited list to vars
                dflow.vars['visited'] = dflow.visited
                results[ dname ] = dflow.vars

    return results  

def make_switchDict( switches, linkDefs):
    switchDict = defaultdict(list)

    for (n1,n2) in linkDefs:
        link = n1+'-'+n2
        switchDict[n1].append(link)
        switchDict[n2].append(link)

    for sw in switches.keys():
        # for disconnected switches that have no neighbors, will have an empty list
        if sw not in switchDict:
            switchDict[sw] = []

    print(switchDict)
    return switchDict

def findFlows(top_file,rule_file,ipn_file,mh,out_file,sess_file,sw_file):
    global MatchNewlySeen, RuleNewlySeen, ActionNewlySeen
   
    resetGlobalVariables()
 
    #parseArgs(cmd_array)
    output_file = out_file
    session_file = sess_file
    switch_file = sw_file

    ### topology dictionary is index by node id (e.g. 'n17') with value equal to a list of other 
    ### node ids of neighbors, where we assume that the order in the list corresponds to port numbers
    ### 1, 2, and so on
    topoDict  = readTopoFile( top_file )

    ### rules file has one key 'nodes', which leads to a dictionary indexed by node id (e.g. 'n17')
    ### which leads to a dictionary with a mysterious single key which is a numerical code of some kind,
    ### which leads to a list of dictionaries, each of which describes a rule
    rulesDict = readRulesFile( rule_file )

    ### the ip file describes IP addresses associated with the switches.  The dictionary is
    ### indexed by the node id, maps to a list of CIDR addresses
    ###
    nodeIPs   = readIPFile( ipn_file )

    ### switches is a dictionary indexed by switch (node) id, each mapped to a dictionary
    ### whose integer keys are port numbers and whose value for a port number is the node identity
    ### of a neighbor
    ###
    switches    = buildNetwork(topoDict, rulesDict, nodeIPs )

    ### Here I take the functions mineLinkDefs to create a switch dictionary that uses the switches node
    ### name as keys, and stores all links in array associated with it
    linkDefs = mineLinkDefs(topoDict)
    switchDict = make_switchDict(switches,linkDefs)

    ### the parsing of the topo and rules files may encounter attributes in the rules that we have not seen
    ### before.   These should be flagged for the developer to include in the code
    ###   sets RuleNewlySeen, MatchNewlySeen and ActionNewlySeen are modified in utils/rule.py when
    ### these new attributes are discovered
    ###
    newAttributes = False
    if RuleNewlySeen:
        print('unknown rule attributes seen in configuration, report to developer', repr(RuleNewlySeen),\
                file = sys.stderr)
        newAttributes = True

    if MatchNewlySeen:
        print('unknown match attributes seen in configuration, report to developer', repr(MatchNewlySeen),\
                file=sys.stderr)
        newAttributes = True

    if ActionNewlySeen:
        print('unknown action attributes seen in configuration, report to developer', repr(ActionNewlySeen),\
                file=sys.stderr)
        newAttributes = True

    if newAttributes:
        raise Exception

    buildLinkState( switches, linkState )

    ### save a pointer to the linkState structure in all the switches
    saveLinkState( switches, linkState ) 

    ### create a data structure that aids in routing 
    neighborMap = makeNeighborMap( switches )

    ### find all flows with at least 'minimum_hops' hops between switches
    ###
    resultsDict = findViableFlows( switches, neighborMap, mh = minimum_hops )
  
    ### clean up the flows in resultsDict to remove extraneous attributes
    ###
    for flowName, flow in resultsDict.items():
        cleanUp( flow )
 
    ### record the results to file 
    if output_file:     
        sessionDict = {'command_string':cmd_str,'topo_file':top_file,'rules_file':rule_file,\
             'ip_file':ipn_file,'flows_file':output_file,'switch_file':switch_file}

        with open(session_file,'w') as sf:
            sstr = json.dumps( sessionDict, indent=4 )
            sf.write(sstr)

        with open(output_file,'w') as of:
            estr = json.dumps( resultsDict, indent=4 )
            of.write(estr)

        with open(switch_file,'w') as swf:
            wstr = json.dumps( switchDict, indent=4 )
            swf.write(wstr)
