"""IMAGEBOT — turn a news headline into ready-to-post anime announcement cards.

Pipeline:  news text  ->  parse (LLM or rules)  ->  find art (Google/DDG)
           ->  composite panels (Pillow)        ->  ready-to-post PNG(s)
"""

__version__ = "0.1.0"
