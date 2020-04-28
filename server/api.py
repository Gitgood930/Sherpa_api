#!/usr/bin/env python3
import os, json
from src import findFlows, makeEvals, sherpa
from flask import Flask, request, send_file
from flask_cors import CORS
from werkzeug.utils import secure_filename

app = Flask(__name__)
cors = CORS(app,origins=['http://localhost:*'])
# Create a directory in a known location to save files to.
uploads_dir = 'uploads'
if not os.path.exists(uploads_dir):
    os.makedirs(uploads_dir)
ALLOWED_EXTENSIONS = {'json'}
if app.debug:
    print(os.getcwd())


def allowed_file(filename):
    '''
    Helper Function to make uploaded filenames secure
    '''
    return '.' in filename and \
        filename.rsplit('.',1)[1].lower() in ALLOWED_EXTENSIONS

def ret_json(success=True,status=200,msg=None,sess=None,flows=None,links=None):
    '''
    Helper Function to format json response output
    '''
    if not flows and not links:
        if msg:
            return json.dumps({'success':success,'message':msg}),status,{'ContentType':'application/json'}
        else:
            return json.dumps({'success':success}),status,{'ContentType':'application/json'}
    else:
        return json.dumps({'success':success,'session':sess,'flows':flows,'links':links}),status,{'ContentType':'application/json'}


@app.route('/upload',methods=["POST"])
def upload_config():
    '''
    upload network configuration json files to server
    return flows and links that user can choose to evaluate

    Requst Arguments:
        name:       name of the session
        mh:         the minimum number of hops
    File Arguments:
        topology:   user json input of network topology
        rules:      user json input of network rules
        nodeIPs:    user json input of network IPs
    output:
        sess:       name of the created session for identification
        flows:      the dictionary of flows in this session with given mh
        links:      the list of links in this session with given mh
    '''
    #### Need to make the operation atomic in case of failure
    #parameter check
    if 'name' not in request.args:
        return ret_json(False,404,msg='name argument missing')

    for i in ['topology','rules','nodeIPs']:
        if i not in request.files:
            return ret_json(False,404,msg=i+' file not found')

    # Create experiment session folder to store all files corresponding to the experiment
    exp_name = request.args['name']
    if 'mh' not in request.args:
        mh = 0
    else:
        mh = request.args['mh']
    if not (str.isdigit(mh) and int(mh) > -1):
        return ret_json(False,404,msg='minimum hop should be an positive integer')
    folder_n = exp_name+'_mh_'+str(mh)
    session_n = os.path.join(uploads_dir,folder_n)
    if os.path.exists(session_n):
        return ret_json(False,404,msg='Session already exists, pick another name')
    os.makedirs(session_n)
    # results folder to store experiment results
    os.makedirs(os.path.join(session_n,'results'))
    # evaluation folder to store old evaluations to be reused
    os.makedirs(os.path.join(session_n,'evals'))

    # store topology, rules, nodeIPs
    topology = request.files['topology']
    if topology and allowed_file(topology.filename):
        top_f_name = secure_filename(topology.filename)
        top_path = os.path.join(session_n,top_f_name)
        topology.save(top_path)

    rules = request.files['rules']
    if rules and allowed_file(rules.filename):
        rule_f_name = secure_filename(rules.filename)
        rule_path = os.path.join(session_n,rule_f_name)
        rules.save(rule_path)

    nodeIPs = request.files['nodeIPs']
    if nodeIPs and allowed_file(nodeIPs.filename):
        IP_f_name = secure_filename(nodeIPs.filename)
        IP_path = os.path.join(session_n,IP_f_name)
        nodeIPs.save(IP_path)
    ## run findFlows to get parse files
    sess_file = os.path.join(session_n,'session.json') 
    flows_file = os.path.join(session_n,'flows.json')
    findFlows.findFlows(top_path,rule_path,IP_path,mh,flows_file,sess_file)
    ## return flows and rules with the given configurations
    linksList, flowsDict = makeEvals.get_flows_rules(sess_file)
    # create response json returning flows and rules of session
    return ret_json(sess=exp_name,flows=flowsDict,links=linksList) 

@app.route('/load',methods=["GET"])
def load_config():
    '''
    load in configuration to use
    return flows and links that user can choose to evaluate
    
    Request Arguments:
        sess:       the session folder to be used
    output:
        session:    the session name
        flows:      the list of flows in this session with given mh
        links:      the list of links in this session with given mh
    '''
    if 'session_name' not in request.args:
        return ret_json(False,404,msg='file name not provided')
    # check if session exists in uploads folder
    sess = request.args["session_name"]
    session_n = os.path.join(uploads_dir,sess)
    if not os.path.exists(session_n):
        return ret_json(False,404,msg='Session does not exist')
    sess_file = os.path.join(session_n,'session.json')
    linksList, flowsDict = makeEvals.get_flows_rules(sess_file)
    # get session file and run makeEvals, and return the links and flows
    return ret_json(sess=sess,flows=flowsDict,links=linksList)

@app.route('/sessions',methods=["GET"])
def get_sessions():
    '''
    get a list of all the configurations that were saved to file

    output:
        sessions:   list of all sessions created by the user
    '''
    configs = []
    configs = os.listdir(uploads_dir)
    for file in configs:
        # remove hidden files
        if file.startswith('.'):
            configs.remove(file)
    return json.dumps({'success':True,'sessions': configs}),200,{'ContentType':'application/json'}

@app.route('/run',methods=["POST"])
def run_sherpa():
    '''
    run experiment with evaluation
    from selected links and flows to evaluate, run sherpa on

    Request Arguments:
        session_name: the session to pull previously uploaded data from
        eval_name:    name of user specified evaluation
    JSON Arguments:
        flows:        array of user selected flows to evaluate
        links:        array of user selected links to evaluate
    output:
        output file:  json output of experiment ran on evaluation
    '''
    #### Need to make atomic in case of operation failure

    if 'session_name' not in request.args:
        return ret_json(False,404,msg='file name not provided')
    # check if session exists in uploads folder
    sess = request.args["session_name"]
    session_n = os.path.join(uploads_dir,sess)
    if not os.path.exists(session_n):
        return ret_json(False,404,msg='Session does not exist')
    sess_file = os.path.join(session_n,'session.json')

    # create evaluation and output file path
    if "eval_name" not in request.args:
        return ret_json(False,404,msg='evaluation name not provided')
    eval_n = request.args['eval_name']
    out_n = eval_n + '_out.json'
    eval_n = eval_n + '_eval.json'
    eval_file = os.path.join(session_n,"evals",eval_n)
    out_file = os.path.join(session_n,"results",out_n)

    # get selected flows and links array
    form_json = request.get_json()
    flows = form_json['flows']
    links = form_json['links']

    # run evalution on chosen flows and links
    makeEvals.make_Eval(sess_file,eval_file,flows,links)
    # run experiment from created evaluation
    sherpa.run_exp(eval_file,out_file)
    # fetch experiment file and return it
    return send_file(out_file,as_attachment=True)


@app.route('/evals',methods=["GET"])
def get_evals():
    '''
    To be made in the next step.
    This Api will get list of all evaluations corresponding to
    this session.

    Request Arguments:
        session_name: name of the session upload
    output:
        evaluations:  list of the evaluations that were previously created
    '''
    if 'session_name' not in request.args:
        return ret_json(False,404,msg='file name not provided')
    # check if session exists in uploads folder
    sess = request.args["session_name"]
    session_n = os.path.join(uploads_dir,sess)
    if not os.path.exists(session_n):
        return ret_json(False,404,msg='Session does not exist')
    eval_fol_p = os.path.join(session_n,'evals')
    if not os.path.exists(eval_fol_p):
        return ret_json(False,404,msg='Evalution Folder does not exist')

    evals = []
    for file in os.listdir(eval_fol_p):
        # only add evaluation files to return response
        if file.endswith('_eval.json'):
            evals.append(file)
    return json.dumps({'success':True,'evaluations': evals}),200,{'ContentType':'application/json'}


@app.route('/load_evals',methods=["GET"])
def load_eval():
    '''
    To be made in the next step.
    This Api will allow users to load evaluations to the 
    eval file before submitting to run experiment
    '''
    pass

@app.route('/rm_eval',methods=["DELETE"])
def rm_eval():
    '''
    To be made in the next step.
    This API will allow users to remove old evalutions
    from the eval folder
    '''
    pass

if __name__ == '__main__':
    app.run(debug=True)