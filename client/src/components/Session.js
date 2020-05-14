import React, {Component} from 'react';
import {withRouter, NavLink, Switch, Route} from 'react-router-dom';
import Button from 'react-bootstrap/Button';

import SwitchMetric from './metrics/SwitchMetric';
import CriticalFlows from './metrics/CriticalFlows';
import CustomSherpa from './metrics/CustomSherpa';
import OtherMetrics from './metrics/OtherMetrics';

class Session extends Component {
  constructor(props){
    super(props);
    this.state = {
      flows: {},
      links: [],
    };
  }

  componentDidMount() {
    let {session_name} = this.props.match.params;
    console.log(this.props);
    // call fetch
    fetch(`http://localhost:5000/load?session_name=${session_name}`)
    .then(rsp => rsp.json())
    .then(data => {
      console.log(data);
      if (data.success) {
        this.setState({
          success: data.success,
          flows: data.flows,
          links: data.links 
        });
      }
    }).catch(error => console.log('error', error));
  }

  render() {
    if (!this.state.flows || !this.state.links) {
      return (
        <div>
          Loading...
        </div>
      );
    }
    const {history, match} = this.props;
    return (
      <div>
        <Button onClick={() => history.goBack()}>
          Back
        </Button>
        <h2>Session: {match.params.session_name}</h2>
        <div>
          <div>
            <NavLink to={`${match.url}`}>Critical Flows</NavLink>
            <NavLink to={`${match.url}/switch`}>Switch Impact</NavLink>
            <NavLink to={`${match.url}/sherpa`}>Custom SHERPA</NavLink>
            <NavLink to={`${match.url}/others`}>Other Metrics</NavLink>
          </div>
          <Switch>
            <Route path={`${match.path}`} component={CriticalFlows} exact/>
            <Route path={`${match.path}/switch`} component={SwitchMetric}/>
            <Route path={`${match.path}/sherpa`} component={CustomSherpa}/>
            <Route path={`${match.path}/others`} component={OtherMetrics}/>
          </Switch>
        </div>
      </div>
    );
  }
}


export default withRouter(Session);