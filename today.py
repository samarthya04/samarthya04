#!/usr/bin/env python3
"""
today.py — Generates dynamic SVG profile banners with live GitHub stats.
Inspired by github.com/Andrew6rant/Andrew6rant

Fetches GitHub stats (repos, commits, stars, followers, LOC) via the
GitHub GraphQL API and generates dark/light mode SVG files styled as a
syntax-highlighted Python code editor.

Usage:
    Set ACCESS_TOKEN and USER_NAME env vars, then run:
    $ python today.py
"""

import datetime
import json
import os
import time
import requests

# ─── Configuration ───────────────────────────────────────────────────────────

HEADERS = {'authorization': 'token ' + os.environ.get('ACCESS_TOKEN', '')}
USER_NAME = os.environ.get('USER_NAME', 'samarthya04')
CACHE_FILE = os.path.join('cache', 'loc_cache.json')

# ─── GitHub GraphQL API ──────────────────────────────────────────────────────

def graphql_request(query, variables):
    """Execute a GitHub GraphQL request with retry logic."""
    for attempt in range(3):
        response = requests.post(
            'https://api.github.com/graphql',
            json={'query': query, 'variables': variables},
            headers=HEADERS,
            timeout=30
        )
        if response.status_code == 200:
            result = response.json()
            if 'errors' in result:
                print(f'  GraphQL errors: {result["errors"]}')
            return result
        elif response.status_code in (502, 503):
            print(f'  {response.status_code} error, retrying ({attempt + 1}/3)...')
            time.sleep(2 ** attempt)
        else:
            raise Exception(
                f'GraphQL failed: {response.status_code} {response.text}'
            )
    raise Exception('GraphQL request failed after 3 retries')


def get_user_info():
    """Fetch user ID, follower count, and account creation date."""
    query = '''
    query($login: String!) {
        user(login: $login) {
            id
            followers { totalCount }
            createdAt
        }
    }'''
    data = graphql_request(query, {'login': USER_NAME})
    user = data['data']['user']
    return {
        'id': user['id'],
        'followers': user['followers']['totalCount'],
        'created_at': user['createdAt']
    }


def get_total_commits(created_at):
    """Calculate total contributions by querying year-by-year ranges."""
    total = 0
    start = datetime.datetime.fromisoformat(created_at.replace('Z', '+00:00'))
    now = datetime.datetime.now(datetime.timezone.utc)

    query = '''
    query($login: String!, $from: DateTime!, $to: DateTime!) {
        user(login: $login) {
            contributionsCollection(from: $from, to: $to) {
                contributionCalendar { totalContributions }
            }
        }
    }'''

    current = start
    while current < now:
        end = min(current.replace(year=current.year + 1), now)
        variables = {
            'login': USER_NAME,
            'from': current.isoformat(),
            'to': end.isoformat()
        }
        data = graphql_request(query, variables)
        contrib = data['data']['user']['contributionsCollection']
        year_total = contrib['contributionCalendar']['totalContributions']
        total += year_total
        print(f'  {current.year}: {year_total} contributions')
        current = end

    return total


def get_repos_and_stars():
    """Fetch all owned repos with star counts and commit totals."""
    repos = []
    total_stars = 0
    total_repos = 0
    cursor = None

    query = '''
    query($login: String!, $cursor: String) {
        user(login: $login) {
            repositories(first: 100, after: $cursor, ownerAffiliations: [OWNER]) {
                totalCount
                edges {
                    node {
                        nameWithOwner
                        stargazers { totalCount }
                        defaultBranchRef {
                            target {
                                ... on Commit {
                                    history { totalCount }
                                }
                            }
                        }
                    }
                }
                pageInfo { endCursor hasNextPage }
            }
        }
    }'''

    while True:
        data = graphql_request(query, {'login': USER_NAME, 'cursor': cursor})
        repo_data = data['data']['user']['repositories']
        total_repos = repo_data['totalCount']

        for edge in repo_data['edges']:
            node = edge['node']
            total_stars += node['stargazers']['totalCount']
            commit_count = 0
            if (node.get('defaultBranchRef')
                    and node['defaultBranchRef'].get('target')):
                commit_count = (
                    node['defaultBranchRef']['target']['history']['totalCount']
                )

            owner, name = node['nameWithOwner'].split('/', 1)
            repos.append({
                'owner': owner,
                'name': name,
                'full_name': node['nameWithOwner'],
                'commit_count': commit_count
            })

        if repo_data['pageInfo']['hasNextPage']:
            cursor = repo_data['pageInfo']['endCursor']
        else:
            break

    return total_repos, total_stars, repos


def get_loc_for_repo(owner, name, user_id):
    """Iterate through all commits in a repo, summing LOC by the user."""
    query = '''
    query($owner: String!, $name: String!, $cursor: String) {
        repository(name: $name, owner: $owner) {
            defaultBranchRef {
                target {
                    ... on Commit {
                        history(first: 100, after: $cursor) {
                            edges {
                                node {
                                    additions
                                    deletions
                                    author { user { id } }
                                }
                            }
                            pageInfo { endCursor hasNextPage }
                        }
                    }
                }
            }
        }
    }'''

    additions = 0
    deletions = 0
    cursor = None

    while True:
        data = graphql_request(
            query, {'owner': owner, 'name': name, 'cursor': cursor}
        )
        repo = data.get('data', {}).get('repository')
        if not repo or not repo.get('defaultBranchRef'):
            break

        target = repo['defaultBranchRef'].get('target')
        if not target or 'history' not in target:
            break

        history = target['history']
        for edge in history.get('edges', []):
            node = edge['node']
            author = node.get('author')
            if (author and author.get('user')
                    and author['user']['id'] == user_id):
                additions += node['additions']
                deletions += node['deletions']

        if history['pageInfo']['hasNextPage']:
            cursor = history['pageInfo']['endCursor']
            time.sleep(0.3)
        else:
            break

    return additions, deletions


def get_total_loc(repos, user_id):
    """Calculate total LOC across all repos, using a per-repo cache."""
    cache = {}
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, 'r') as f:
            cache = json.load(f)

    total_add = 0
    total_del = 0

    for repo in repos:
        key = repo['full_name']

        # Use cache if commit count hasn't changed
        if key in cache and cache[key].get('commits') == repo['commit_count']:
            total_add += cache[key]['additions']
            total_del += cache[key]['deletions']
            print(f'  [cache] {key}: '
                  f'+{cache[key]["additions"]:,} / -{cache[key]["deletions"]:,}')
            continue

        # Fetch fresh data
        print(f'  [fetch] {key}...', end=' ', flush=True)
        try:
            add, delete = get_loc_for_repo(
                repo['owner'], repo['name'], user_id
            )
            cache[key] = {
                'additions': add,
                'deletions': delete,
                'commits': repo['commit_count']
            }
            total_add += add
            total_del += delete
            print(f'+{add:,} / -{delete:,}')
        except Exception as e:
            print(f'Error: {e}')
            if key in cache:
                total_add += cache[key].get('additions', 0)
                total_del += cache[key].get('deletions', 0)

        time.sleep(0.5)

    # Persist cache
    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    with open(CACHE_FILE, 'w') as f:
        json.dump(cache, f, indent=2)

    return total_add, total_del


# ─── SVG Generation ──────────────────────────────────────────────────────────

THEMES = {
    'dark': {
        'bg': '#161b22',   'text': '#c9d1d9', 'ln': '#484f58',
        'kw': '#ff7b72',   'fn':  '#d2a8ff',  'st': '#a5d6ff',
        'nm': '#79c0ff',   'cm':  '#8b949e',  'vr': '#ffa657',
        'ad': '#3fb950',   'dl':  '#f85149',  'ascii': '#484f58',
    },
    'light': {
        'bg': '#f6f8fa',   'text': '#24292f', 'ln': '#8c959f',
        'kw': '#cf222e',   'fn':  '#8250df',  'st': '#0a3069',
        'nm': '#0550ae',   'cm':  '#6e7781',  'vr': '#953800',
        'ad': '#1a7f37',   'dl':  '#cf222e',  'ascii': '#8c959f',
    }
}

def generate_svg(theme, stats):
    """Build a complete SVG string for the given colour theme."""
    c = THEMES[theme]
    today = datetime.datetime.now().strftime('%b %d, %Y')

    # Helper: wrap text in a colored tspan
    def col(color_key, text):
        return f'<tspan fill="{c[color_key]}">{text}</tspan>'

    # Helper: build one full line (line-number + content)
    def line(y, num, content='', x_offset=370):
        ln = col('ln', f'{num:>2}')
        if not content:
            return f'<tspan x="{x_offset}" y="{y}">{ln}</tspan>'
        return f'<tspan x="{x_offset}" y="{y}">{ln}  {content}</tspan>'

    sep = '=' * 74

    # fmt: off
    lines = [
        line( 35,  1, col('cm', f'# {sep}')),
        line( 55,  2, col('cm', '#  samarthya04/README.py                Computer Vision &amp; Diffusion Models')),
        line( 75,  3, col('cm', f'# {sep}')),
        line( 95,  4),
        line(115,  5, f'{col("kw","class")} {col("fn","SamarthyaChattree")}:'),
        line(135,  6, f'    {col("st",chr(34)*3+"Associate Software Engineer @ Blackbaud"+chr(34)*3)}'),
        line(155,  7),
        line(175,  8, f'    {col("vr","name")}       = {col("st",chr(34)+"Samarthya Earnest Chattree"+chr(34))}'),
        line(195,  9, f'    {col("vr","role")}       = {col("st",chr(34)+"Associate Software Engineer @ Blackbaud"+chr(34))}'),
        line(215, 10, f'    {col("vr","research")}   = {col("st",chr(34)+"Hi-MambaSR: Hierarchical State-Space Refinement"+chr(34))}'),
        line(235, 11, f'    {col("vr","education")}  = {col("st",chr(34)+"B.Tech CSE, KIIT (8.86 CGPA)"+chr(34))}'),
        line(255, 12),
        line(275, 13, f'    {col("cm","# GitHub Statistics")}                          {col("cm","# updated: "+today)}'),
        line(295, 14, f'    {col("vr","repos")}      = {col("nm", stats["repos"])}'),
        line(315, 15, f'    {col("vr","commits")}    = {col("nm", stats["commits"])}'),
        line(335, 16, f'    {col("vr","stars")}      = {col("nm", stats["stars"])}'),
        line(355, 17, f'    {col("vr","followers")}  = {col("nm", stats["followers"])}'),
        line(375, 18),
        line(395, 19, f'    {col("vr","lines_changed")} = {col("st",chr(34))}{col("ad",stats["loc_added"]+"++")}{col("st"," / ")}{col("dl",stats["loc_deleted"]+"--")}{col("st",chr(34))}'),
        line(415, 20),
        line(435, 21, f'    {col("vr","languages")}  = [{col("st",chr(34)+"Python"+chr(34))}, {col("st",chr(34)+"C#"+chr(34))}, {col("st",chr(34)+"Java"+chr(34))}, {col("st",chr(34)+"PyTorch"+chr(34))}]'),
        line(455, 22, f'    {col("vr","tools")}      = [{col("st",chr(34)+".NET"+chr(34))}, {col("st",chr(34)+"Docker"+chr(34))}, {col("st",chr(34)+"Azure DevOps"+chr(34))}, {col("st",chr(34)+"GCP"+chr(34))}]'),
    ]
    # fmt: on

    tspans = '\n'.join(lines)
    
    # Generate ASCII art tspans dynamically from file
    ascii_file_path = os.path.join(os.path.dirname(__file__), 'ascii-art.txt')
    try:
        with open(ascii_file_path, 'r', encoding='utf-8') as f:
            raw_lines = f.read().splitlines()
            non_empty = [line for line in raw_lines if line.strip()]
            if non_empty:
                min_indent = min(len(line) - len(line.lstrip()) for line in non_empty)
                ascii_art = [line[min_indent:].rstrip() for line in raw_lines]
            else:
                ascii_art = raw_lines
    except FileNotFoundError:
        ascii_art = ["ASCII art missing"]

    def escape_xml(text):
        return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

    ascii_tspans = []
    y = 20
    for row in ascii_art:
        # Use smaller font-size to fit 56 lines into 480px height
        ascii_tspans.append(f'<tspan x="30" y="{y}" fill="{c["ascii"]}" font-size="8px">{escape_xml(row)}</tspan>')
        y += 8
        
    ascii_group = '\n'.join(ascii_tspans)

    return f'''<?xml version='1.0' encoding='UTF-8'?>
<svg xmlns="http://www.w3.org/2000/svg" font-family="ConsolasFallback,Consolas,monospace" width="1120px" height="480px" font-size="15px">
<style>
@font-face {{
src: local('Consolas'), local('Consolas Bold');
font-family: 'ConsolasFallback';
font-display: swap;
-webkit-size-adjust: 109%;
size-adjust: 109%;
}}
text, tspan {{white-space: pre;}}
</style>
<rect width="1120px" height="480px" fill="{c['bg']}" rx="15"/>
<text x="15" y="30" fill="{c['text']}">
{ascii_group}
{tspans}
</text>
</svg>'''


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    start_time = time.time()

    print(f'=== Profile SVG Generator for {USER_NAME} ===\n')

    if not os.environ.get('ACCESS_TOKEN'):
        print('ACCESS_TOKEN not set. Using placeholder stats.')
        stats = {
            'repos':       '0',
            'commits':     '0',
            'stars':       '0',
            'followers':   '0',
            'loc_added':   '0',
            'loc_deleted': '0',
        }
    else:
        print('Fetching user info...')
        user_info = get_user_info()
        print(f'  User ID: {user_info["id"]}')
        print(f'  Created: {user_info["created_at"]}')
        print(f'  Followers: {user_info["followers"]}\n')
    
        print('Fetching total commits...')
        total_commits = get_total_commits(user_info['created_at'])
        print(f'  Total: {total_commits:,}\n')
    
        print('Fetching repos and stars...')
        total_repos, total_stars, repos = get_repos_and_stars()
        print(f'  Repos: {total_repos}')
        print(f'  Stars: {total_stars}')
        print(f'  Repos to scan for LOC: {len(repos)}\n')
    
        print('Calculating lines of code...')
        loc_added, loc_deleted = get_total_loc(repos, user_info['id'])
        print(f'  Total: +{loc_added:,} / -{loc_deleted:,}\n')
    
        stats = {
            'repos':       f'{total_repos:,}',
            'commits':     f'{total_commits:,}',
            'stars':       f'{total_stars:,}',
            'followers':   f'{user_info["followers"]:,}',
            'loc_added':   f'{loc_added:,}',
            'loc_deleted': f'{loc_deleted:,}',
        }

    print('Generating SVGs...')
    for theme in ('dark', 'light'):
        svg = generate_svg(theme, stats)
        filename = f'{theme}_mode.svg'
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(svg)
        print(f'  Wrote {filename}')

    elapsed = time.time() - start_time
    print(f'\nDone in {elapsed:.1f}s')


if __name__ == '__main__':
    main()
