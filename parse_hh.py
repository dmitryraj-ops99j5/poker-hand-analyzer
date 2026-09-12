import re
import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Iterator

@dataclass
class PlayerAction:
    name: str
    action: str
    amount: float = 0.0

@dataclass
class Hand:
    hand_id: str
    game_type: str
    blinds: tuple
    players: list
    preflop_actions: list
    flop_actions: list
    turn_actions: list
    river_actions: list
    community_cards: list = field(default_factory=list)
    showdown: list = field(default_factory=list)
    winners: list = field(default_factory=list)

def _parse_money(s: str) -> float:
    s = s.replace('$', '').replace(',', '')
    try:
        return float(s)
    except ValueError:
        return 0.0

def _extract_players(lines: list) -> list:
    players = []
    for line in lines:
        if 'Seat' in line and 'in chips' in line:
            m = re.search(r'Seat \d+: (.+?) \((\$?[\d,.]+)', line)
            if m:
                players.append(m.group(1).strip())
    return players

def _extract_blinds(lines: list) -> tuple:
    sb, bb = 0.0, 0.0
    for line in lines:
        if 'posts small blind' in line:
            m = re.search(r'posts small blind (?:\$?)([\d,.]+)', line)
            if m:
                sb = _parse_money(m.group(1))
        elif 'posts big blind' in line:
            m = re.search(r'posts big blind (?:\$?)([\d,.]+)', line)
            if m:
                bb = _parse_money(m.group(1))
    return sb, bb

def _parse_actions_for_section(lines: list, start_marker: str, end_markers: tuple) -> list:
    actions = []
    collecting = False
    for line in lines:
        if start_marker in line and '***' in line:
            collecting = True
            continue
        if collecting and any(m in line for m in end_markers):
            break
        if not collecting:
            continue
        
        line = line.strip()
        if not line or line.startswith('***'):
            continue
        
        if ': folds' in line:
            name = line.split(':')[0].strip()
            actions.append(PlayerAction(name, 'fold'))
        elif ': checks' in line:
            name = line.split(':')[0].strip()
            actions.append(PlayerAction(name, 'check'))
        elif ': calls' in line:
            name = line.split(':')[0].strip()
            m = re.search(r'calls (?:\$?)([\d,.]+)', line)
            amt = _parse_money(m.group(1)) if m else 0.0
            actions.append(PlayerAction(name, 'call', amt))
        elif ': bets' in line:
            name = line.split(':')[0].strip()
            m = re.search(r'bets (?:\$?)([\d,.]+)', line)
            amt = _parse_money(m.group(1)) if m else 0.0
            actions.append(PlayerAction(name, 'bet', amt))
        elif ': raises' in line:
            name = line.split(':')[0].strip()
            m = re.search(r'to (?:\$?)([\d,.]+)', line)
            amt = _parse_money(m.group(1)) if m else 0.0
            actions.append(PlayerAction(name, 'raise', amt))
        elif ': is all-in' in line:
            name = line.split(':')[0].strip()
            actions.append(PlayerAction(name, 'allin'))
    
    return actions

def _extract_showdown(lines: list) -> list:
    showdown = []
    in_showdown = False
    for line in lines:
        if '*** SHOWDOWN ***' in line:
            in_showdown = True
            continue
        if in_showdown and line.startswith('***'):
            break
        if in_showdown and ': shows' in line:
            name = line.split(':')[0].strip()
            showdown.append(name)
    return showdown

def _extract_winners(lines: list) -> list:
    winners = []
    for line in lines:
        # split pot can have multiple "collected" lines
        if 'collected' in line and 'from pot' in line:
            m = re.search(r'(.+?) collected', line)
            if m:
                winners.append(m.group(1).strip())
        elif 'won' in line and 'pot' in line:
            m = re.search(r'(.+?) won', line)
            if m:
                winners.append(m.group(1).strip())
    return winners

def _extract_community_cards(lines: list) -> list:
    cards = []
    for line in lines:
        if '*** FLOP ***' in line:
            m = re.search(r'\[([^\]]+)\]', line)
            if m:
                cards.extend(m.group(1).split())
        elif '*** TURN ***' in line:
            m = re.search(r'\[([^\]]+)\]', line)
            if m:
                cards.extend(m.group(1).split())
        elif '*** RIVER ***' in line:
            m = re.search(r'\[([^\]]+)\]', line)
            if m:
                cards.extend(m.group(1).split())
    return cards

def _parse_hand(block: str) -> Hand | None:
    lines = block.strip().split('\n')
    if not lines:
        return None
    
    hand_id = ''
    game_type = ''
    for line in lines:
        if 'PokerStars Hand #' in line:
            m = re.search(r'Hand #(\d+)', line)
            if m:
                hand_id = m.group(1)
            if '(' in line and ')' in line:
                game_type = line.split('(')[-1].split(')')[0]
            break
    
    if not hand_id:
        return None
    
    players = _extract_players(lines)
    blinds = _extract_blinds(lines)
    
    pf_actions = _parse_actions_for_section(
        lines, '*** HOLE CARDS ***', ('*** FLOP ***', '*** SUMMARY ***')
    )
    flop_actions = _parse_actions_for_section(
        lines, '*** FLOP ***', ('*** TURN ***', '*** SUMMARY ***')
    )
    turn_actions = _parse_actions_for_section(
        lines, '*** TURN ***', ('*** RIVER ***', '*** SUMMARY ***')
    )
    river_actions = _parse_actions_for_section(
        lines, '*** RIVER ***', ('*** SHOWDOWN ***', '*** SUMMARY ***')
    )
    
    community = _extract_community_cards(lines)
    showdown = _extract_showdown(lines)
    winners = _extract_winners(lines)
    
    return Hand(
        hand_id=hand_id,
        game_type=game_type,
        blinds=blinds,
        players=players,
        preflop_actions=pf_actions,
        flop_actions=flop_actions,
        turn_actions=turn_actions,
        river_actions=river_actions,
        community_cards=community,
        showdown=showdown,
        winners=winners,
    )

def parse_file(path: str | Path) -> Iterator[Hand]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"hand history not found: {p}")
    
    text = p.read_text(encoding='utf-8', errors='ignore')
    
    # split on blank lines between hands
    blocks = re.split(r'\n\n+', text)
    
    for block in blocks:
        block = block.strip()
        if not block or 'PokerStars Hand #' not in block:
            continue
        hand = _parse_hand(block)
        if hand:
            yield hand

def player_vpip(hands: list[Hand], player_name: str) -> float:
    vpip_hands = 0
    total = 0
    for hand in hands:
        if player_name not in hand.players:
            continue
        total += 1
        acted = False
        for a in hand.preflop_actions:
            if a.name == player_name:
                if a.action in ('call', 'raise', 'bet', 'allin'):
                    acted = True
                    break
        if acted:
            vpip_hands += 1
    if total == 0:
        return 0.0
    return vpip_hands / total

def player_pfr(hands: list[Hand], player_name: str) -> float:
    pfr_hands = 0
    total = 0
    for hand in hands:
        if player_name not in hand.players:
            continue
        total += 1
        raised = False
        for a in hand.preflop_actions:
            if a.name == player_name and a.action in ('raise', 'allin'):
                raised = True
                break
        if raised:
            pfr_hands += 1
    if total == 0:
        return 0.0
    return pfr_hands / total

def player_win_rate(hands: list[Hand], player_name: str) -> float:
    wins = 0
    total = 0
    for hand in hands:
        if player_name not in hand.players:
            continue
        total += 1
        if player_name in hand.winners:
            wins += 1
    if total == 0:
        return 0.0
    return wins / total

def player_cbet(hands: list[Hand], player_name: str) -> float:
    """Continuation bet %: bet flop after being last preflop aggressor."""
    cbet_opps = 0
    cbets = 0
    for hand in hands:
        if player_name not in hand.players:
            continue
        
        # must have seen flop
        if not hand.flop_actions:
            continue
        
        # last preflop aggressor
        last_aggressor = None
        for a in reversed(hand.preflop_actions):
            if a.action in ('raise', 'bet', 'allin'):
                last_aggressor = a.name
                break
        
        if last_aggressor != player_name:
            continue
        
        cbet_opps += 1
        
        # check if player bet on flop
        for a in hand.flop_actions:
            if a.name == player_name and a.action in ('bet', 'raise', 'allin'):
                cbets += 1
                break
    
    if cbet_opps == 0:
        return 0.0
    return cbets / cbet_opps
