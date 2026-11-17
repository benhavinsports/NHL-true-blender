"""G18 is ONLY the final Core 3 (Core 2 on two-game slates).

All player decisions must be made by original G0-G17, independent
Step0-Step14 overlay and G10.5. No scorer is chosen, ranked or eliminated
by a new rule inside G18. These are synthetic execution fixtures only.
"""
from nhl_true_blender_engine.engine import cross_game_winners


def survivor(game_id, player_id, route='PRIMARY'):
    return {
        "game": {"id": str(game_id)},
        "candidate": {
            "player": {"id": str(player_id), "name": f"Fixture {player_id}"},
            "route": route,
            "complete": True,
            "dispositions": {"G17": {"disposition": "PASS"}},
        },
    }


def test_g18_only_places_three_distinct_game_survivors_on_core():
    finalists=[
        survivor(100,1,'PRIMARY'),
        survivor(200,2,'TRANSFER'),
        survivor(300,3,'WHO'),
    ]
    original_ids=[id(x) for x in finalists]
    core,errors=cross_game_winners(finalists,11)
    assert not errors
    assert [id(x) for x in core]==original_ids
    assert [x["candidate"]["route"] for x in core]==[
        'PRIMARY','TRANSFER','WHO']
    assert {x["game"]["id"] for x in core}=={'100','200','300'}


def test_g18_only_places_two_distinct_game_survivors_on_two_game_card():
    finalists=[survivor(100,1),survivor(200,2,'TRANSFER')]
    core,errors=cross_game_winners(finalists,2)
    assert not errors
    assert core==finalists


def test_g18_never_invents_ranking_or_picks_three_of_five():
    finalists=[
        survivor(100,1),survivor(200,2),survivor(300,3),
        survivor(400,4),survivor(500,5)]
    before=[repr(x) for x in finalists]
    core,errors=cross_game_winners(finalists,11)
    assert core==[]
    assert "PRE_CORE_REVIEW" in str(errors)
    assert "G18 cannot" in str(errors)
    assert [repr(x) for x in finalists]==before


def test_g18_does_not_choose_a_scorer_from_two_same_game_survivors():
    finalists=[survivor(100,1),survivor(100,2),survivor(200,3)]
    core,errors=cross_game_winners(finalists,3)
    assert core==[]
    assert "same game" in str(errors)


def test_g18_does_not_fabricate_missing_third_leg():
    core,errors=cross_game_winners([survivor(100,1),survivor(200,2)],9)
    assert core==[]
    assert "PRE_CORE_REVIEW" in str(errors)


def test_g18_does_not_force_labels_or_remove_whos():
    finalists=[survivor(100,1,'PRIMARY'),survivor(200,2,'PRIMARY'),
               survivor(300,3,'PRIMARY')]
    core,errors=cross_game_winners(finalists,9)
    assert not errors
    assert [x["candidate"]["route"] for x in core]==['PRIMARY']*3
