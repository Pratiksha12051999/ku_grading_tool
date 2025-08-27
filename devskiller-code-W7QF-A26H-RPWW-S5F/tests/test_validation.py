import pytest

from q13 import solve


def strip_lines(s: str) -> str:
    return "\n".join(line.strip() for line in s.splitlines())


# List of test cases in the form [(input, output)]
TEST_CASES = [
    (
        strip_lines(
            """AWHILE
            REALISM
            SPEAK
            #
            WILLIAM SHAKESPEARE
            #"""
        ),
        {
            "WILLIAM SHAKESPEARE": [
                ["AWHILE", "REALISM", "SPEAK"],
                ["AWHILE", "SPEAK", "REALISM"],
                ["REALISM", "AWHILE", "SPEAK"],
                ["REALISM", "SPEAK", "AWHILE"],
                ["SPEAK", "AWHILE", "REALISM"],
                ["SPEAK", "REALISM", "AWHILE"],
            ],
        },
    ),
    (
        strip_lines(
            """ABC
            AND
            DEF
            DXZ
            K
            KX
            LJSRT
            LT
            PT
            PTYYWQ
            Y
            YWJSRQ
            ZD
            ZZXY
            #
            XK XYZZ Y
            #"""
        ),
        {
            "XK XYZZ Y": [
                ["KX", "Y", "ZZXY"],
                ["KX", "ZZXY", "Y"],
                ["Y", "KX", "ZZXY"],
                ["Y", "ZZXY", "KX"],
                ["ZZXY", "KX", "Y"],
                ["ZZXY", "Y", "KX"],
            ],
        },
    ),
]


@pytest.mark.parametrize("input,expected", TEST_CASES)
def test_solver(input, expected):
    results = solve(input)
    results_sorted = {phrase: sorted(anagrams) for phrase, anagrams in results.items()}
    assert results_sorted == expected
