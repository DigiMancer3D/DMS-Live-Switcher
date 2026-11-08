"""Pure rules for the six independent Pre-Show tether triggers.

Tether rows are an expandable list (three initial blanks, no three-row cap).
Legacy on_change and on_hide are expanded on load, preserving prior saves.
"""
from copy import deepcopy
PAGES=('dc_load','sb_load','dc_change','sb_change','dc_hide','sb_hide')
DELAYS=(10,30,60)
MIN_ROWS=3  # Editor viewport height / backwards-compatible initial blank rows.
BLANK_ID='dms://blank'

def empty_row():
    return {'board':None,'deck':None,'rules':{p:{'enabled':False,'delays':[]} for p in PAGES}}

def normalize_row(raw):
    if not isinstance(raw,dict):raise ValueError('Tether row must be an object')
    row=empty_row()
    for field in ('board','deck'):
        item=raw.get(field)
        if item is not None:
            if not isinstance(item,dict):raise ValueError('Invalid tether endpoint')
            keys=('path','name') if field=='board' else ('source','id','name')
            if not all(isinstance(item.get(k),str) and item[k] for k in keys):raise ValueError('Incomplete tether endpoint')
            entry={k:item[k] for k in keys}
            # Older alpha saved the generated path, which is specific to its machine.
            if field=='board' and (entry['name'].upper()=='BLANK' and entry['path'].endswith('/blank_pinboard.sboard')):
                entry['path']=BLANK_ID
            row[field]=entry
    rules=raw.get('rules',{})
    if not isinstance(rules,dict):raise ValueError('Invalid tether rules')
    # In v0.1.0-alpha.4, On Change ran in both directions; On Hide meant DC Hide.
    if 'on_change' in rules:
        rules={**rules,'dc_change':rules.get('dc_change',rules['on_change']),
                        'sb_change':rules.get('sb_change',rules['on_change'])}
    if 'on_hide' in rules:
        rules={**rules,'dc_hide':rules.get('dc_hide',rules['on_hide'])}
    for p in PAGES:
        r=rules.get(p,{})
        if not isinstance(r,dict):raise ValueError('Invalid tether rule')
        delays=r.get('delays',[])
        if not isinstance(delays,list) or any(type(d) is not int or d not in DELAYS for d in delays):raise ValueError('Invalid tether delay')
        row['rules'][p]={'enabled':bool(r.get('enabled',False)),'delays':sorted(set(delays))}
    return row

def normalize_tethers(raw,strict=False):
    if not isinstance(raw,list):
        if strict:raise ValueError('Tethers must be a list')
        raw=[]
    # Validate every row: alpha.6 silently sliced rows 4+ on startup, which
    # would otherwise erase newly created tethers from saved state and .dms.
    result=[]
    for row in raw:
        try:result.append(normalize_row(row))
        except ValueError:
            if strict:raise
    while len(result)<MIN_ROWS:result.append(empty_row())
    return result

def delay_seconds(rule):return sum(rule['delays'])

def matching_actions(rows,kind,key):
    """A trigger fires only when its specific source event is observed.

    kind: dc_load / sb_load / dc_change / sb_change / dc_hide / sb_hide.
    key: deck (store,id) or board path/BLANK_ID.
    """
    # Keep old API names available to any older local test integrations.
    kind={'deck':'dc_load','board':'sb_load','hide':'dc_hide'}.get(kind,kind)
    result=[];seen=set()
    for row in rows:
        board=row['board'];deck=row['deck']
        if not board or not deck:continue
        if kind.startswith('dc_'):
            if (deck['source'],deck['id'])!=key:continue
            target='board';entry=board
        elif kind.startswith('sb_'):
            if board['path']!=key:continue
            target='deck';entry=deck
        else:continue
        rule=row['rules'].get(kind)
        if not rule or not rule['enabled']:continue
        token=(target,entry['path'] if target=='board' else (entry['source'],entry['id']),delay_seconds(rule))
        if token in seen:continue
        seen.add(token)
        result.append({'target':target,'entry':deepcopy(entry),'delay':delay_seconds(rule),'trigger':kind})
    return result

def detach_matching(rows,index,all_matches):
    rows=deepcopy(rows)
    selected=rows[index]
    if all_matches:
        b=selected['board'];d=selected['deck']
        remaining=[r for i,r in enumerate(rows) if i!=index and not ((b and r['board'] and r['board']['path']==b['path']) or (d and r['deck'] and (r['deck']['source'],r['deck']['id'])==(d['source'],d['id'])))]
    else:remaining=[r for i,r in enumerate(rows) if i!=index]
    return normalize_tethers(remaining)


def delete_tether_row(rows,index):
    """Delete exactly one row, retaining the three-blank minimum for the editor."""
    if index < 0 or index >= len(rows):
        raise IndexError('Tether row outside range')
    return normalize_tethers([deepcopy(r) for i,r in enumerate(rows) if i != index])


def remove_row_triggers(rows,index):
    """Disable every trigger and remove every delay on one row, keeping its pair."""
    if index < 0 or index >= len(rows):
        raise IndexError('Tether row outside range')
    updated=deepcopy(rows)
    updated[index]['rules']=empty_row()['rules']
    return updated


def clear_all_fields(rows):
    """Erase both endpoints and every rule on ALL rows, preserving row count."""
    return [empty_row() for _ in range(max(MIN_ROWS,len(rows)))]
