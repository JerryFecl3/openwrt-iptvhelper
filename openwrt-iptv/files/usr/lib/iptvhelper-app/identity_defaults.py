"""Derive platform identity exclusively from the selected network interface."""
def resolve(settings,interface_config,system_hostname,device_mac):
    result=dict(settings)
    name=result.get('interface') or 'iptv'
    hostname=interface_config(name).get('hostname','')
    # '*' is udhcpc's no-hostname sentinel, never a platform identity.
    result['stb_id']=hostname if hostname and hostname!='*' else system_hostname()
    result['mac']=device_mac(name).upper()
    return result
