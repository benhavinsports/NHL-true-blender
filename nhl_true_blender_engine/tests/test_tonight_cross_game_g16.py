"""Cross-game G16 compares source-backed opponent matchup BEFORE old goals."""
from nhl_true_blender_engine.engine import g16_cross_game_finalists
from nhl_true_blender_engine.tests.test_g16_cross_game_finalists import finalist
from nhl_true_blender_engine.tests.test_engine import evidence


def aligned(game, pid, old_goals, goalie_percentile, defense_ratio):
    x=finalist(game,pid,old_goals,old_goals+10,goalie='CONFIRMED',dep='CONFIRMED')
    x["attackTeam"]="AWAY"
    x["targetGoalie"]["sourceUrl"]="https://nhl.com/goalies/"+str(game)
    x["targetGoalie"]["data"]["weakZones"]={
        "Low Slot": {
            "leagueSavePctgPercentile":goalie_percentile,
            "shotsAgainst":60,
            "goalsAgainst":12,
            "sourceUrl":"https://nhl.com/goalie-lane/"+str(game),
        }
    }
    x["game"]["coverage"]={"AWAY":evidence({
        "zoneConcessions":{"Low Slot":{
            "onNetShotsPerGame":defense_ratio*8,
            "peerMedianOnNetShotsPerGame":8.0,
            "independentOnNetConcessionReview":True,
            "positiveConcessionBases":["ON_NET_SHOTS_AGAINST_PEER"],
        }}
    },source="https://nhl.com/opponent-defense/"+str(game))}
    return x


def test_matchup_dominates_even_if_old_goals_rank_it_last():
    rows=[
        aligned(1,'a',1,.05,2.0),
        aligned(2,'b',2,.10,1.9),
        aligned(3,'c',3,.15,1.8),
        aligned(4,'d',12,.85,1.1),
    ]
    winners, report=g16_cross_game_finalists(rows,3)
    assert [x['candidate']['player']['id'] for x in winners]==['a','b','c']
    assert report['excludedPlayerIds']==['d']
    assert all(x['g16ComparisonBasis']=='TONIGHT_MATCHUP_OPPONENT_EXPOSURE'
               for x in report['finalists'])
    assert sorted(report['finalists'][3]['dominatedBy'])==['a','b','c']


def test_conflicting_matchup_metrics_do_not_use_old_goals_to_force_a_core():
    rows=[
        aligned(1,'a',1,.05,1.1),
        aligned(2,'b',2,.10,1.2),
        aligned(3,'c',3,.15,1.3),
        aligned(4,'d',12,.85,2.0),
    ]
    winners, report=g16_cross_game_finalists(rows,3)
    assert len(winners)==4
    assert report['separated'] is False
    assert all(x['g16Decision']=='RETAINED' for x in report['finalists'])


def test_incomplete_matchup_scope_cannot_dominate_sourced_scope():
    rows=[
        aligned(1,'a',1,.05,2.0),
        aligned(2,'b',2,.10,1.9),
        aligned(3,'c',3,.15,1.8),
        aligned(4,'d',12,.85,1.1),
    ]
    rows[3]['game']['coverage']['AWAY']['data']['zoneConcessions']['Low Slot'].pop(
        'independentOnNetConcessionReview')
    winners, report=g16_cross_game_finalists(rows,3)
    assert len(winners)==4
    assert report['separated'] is False
    assert report['finalists'][3]['g16ComparisonBasis']=='NOT_COMPARABLE'
    assert report['finalists'][3]['dominatedBy']==[]
