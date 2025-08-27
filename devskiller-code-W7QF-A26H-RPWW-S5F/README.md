It is often fun to see if rearranging the letters of a name gives an amusing anagram. For example, the letters of 'WILLIAM SHAKESPEARE' rearrange to form 'SPEAK REALISM AWHILE'.

Write a program that will read in a dictionary and a list of phrases and determine which words from the dictionary, if any, form anagrams of the given phrases. Your program must find all sets of words in the dictionary which can be formed from the letters in each phrase (ignoring spaces). Each word from the dictionary can only be used once.

The signature of your function should be:

```python
def solve(input: str) -> Dict[str, List[List[str]]]
```

You may implement other functions called by your `solve` function if you wish.

## Input Spec

Input will consist of two parts. The first part is the dictionary in alphabetical order, the second part is the set of phrases for which you need to find anagrams.

Each part of the file will be terminated by a line consisting of a single '#'.

## Output Spec

The output should be a map that contains a key for each of the specified phrases, mapped to a list of possible anagrams (order doesn't matter). If there are no anagrams for a particular phrase, don't include an entry for that phrase in the map.

Each possible anagram is represented as a list of strings.

## Sample Input & Output

Input:

```python
"""IS
THIS
SPARTA
#
ATRAPS
ATRAPS SI
THIS IS SPARTA
#"""
```

Output:

```python
{
  "ATRAPS": [["SPARTA"]],
  "ATRAPS SI": [["IS", "SPARTA"], ["SPARTA", "IS"]],
  "THIS IS SPARTA": [
    ["IS", "SPARTA", "THIS"],
    ["IS", "THIS", "SPARTA"],
    ["SPARTA", "IS", "THIS"],
    ["SPARTA", "THIS", "IS"],
    ["THIS", "IS", "SPARTA"],
    ["THIS", "SPARTA", "IS"],
  ]
}
```