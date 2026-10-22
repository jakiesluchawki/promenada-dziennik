"""Second cooldown check inside serialized Actions jobs, including failed attempts."""
import datetime, json, os, urllib.request

def allowed(runs, current_id, now):
    for run in runs:
        if int(run['id']) >= int(current_id): continue
        started = datetime.datetime.fromisoformat(run['created_at'].replace('Z', '+00:00'))
        if 0 <= (now-started).total_seconds() < 300: return False
    return True

def main():
    workflow = os.environ['MAHBRUS_WORKFLOW']
    if workflow not in ['update.yml','update-student.yml']: raise ValueError('Invalid workflow')
    # The upstream branch query can return an empty history. Enforce it locally.
    url='https://api.github.com/repos/jakiesluchawki/promenada-dziennik/actions/workflows/'+workflow+'/runs?per_page=100'
    request=urllib.request.Request(url,headers={'Authorization':'Bearer '+os.environ['GH_TOKEN'],'Accept':'application/vnd.github+json'})
    with urllib.request.urlopen(request, timeout=20) as response: runs=json.load(response)['workflow_runs']
    runs=[run for run in runs if run.get('head_branch')=='main' and run.get('path')=='.github/workflows/'+workflow]
    due=allowed(runs,os.environ['GITHUB_RUN_ID'],datetime.datetime.now(datetime.timezone.utc))
    with open(os.environ['GITHUB_OUTPUT'],'a') as out: out.write('allowed='+str(due).lower()+'\n')
    print('Collector may run.' if due else 'Another recent attempt covers this cooldown; no login will be made.')
if __name__=='__main__': main()
