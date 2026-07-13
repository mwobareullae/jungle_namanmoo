from __future__ import annotations
import sys,unittest
from pathlib import Path
SCRIPTS=Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:sys.path.insert(0,str(SCRIPTS))
from fresh_riss_search_v1_1 import parse_riss_html,parse_riss_robots_policy,query_url  # noqa:E402

HTML="""<html><span>(검색결과 <span class="num">1</span> 건)</span>
<div class="srchResultListW"><ul><li><input name="p_control_no" value="abc|mat" />
<div><p class="title">A <span>skin</span> paper</p><p class="etc">
<span class="writer"><a>Kim</a>, <a>Lee</a></span><span class="assigned">Society</span>
<span>2024</span><span><a href="/search/detail/DetailView.do?p_mat_type=3a11008f85f7c51d&amp;control_no=j">Journal</a></span>
<span><a href="/search/detail/DetailView.do?p_mat_type=3a11008f85f7c51d&amp;control_no=j&amp;v_control_no=v">Vol. 1</a></span></p>
<ul><li>nested action</li></ul><p class="preAbstract">Measured &lt;b&gt;result&lt;/b&gt;.</p></div></li></ul></div></html>"""

class FreshRissSearchV11Tests(unittest.TestCase):
 def test_parser_extracts_required_metadata_and_ignores_nested_li(self):
  total,papers=parse_riss_html(HTML);self.assertEqual(total,1);self.assertEqual(len(papers),1);p=papers[0]
  self.assertEqual((p.control_no,p.title,p.authors,p.journal,p.publication_year),("abc","A skin paper","Kim, Lee","Journal","2024"));self.assertEqual(p.pre_abstract,"Measured result.")
 def test_query_contract(self):
  query,url=query_url("Niacinamide");self.assertEqual(query,'"Niacinamide" skin');self.assertIn("colName=re_a_kor",url);self.assertIn("strSort=RANK",url);self.assertIn("pageScale=20",url)
 def test_robots_longest_allow_and_delay(self):
  allowed,delay=parse_riss_robots_policy("User-agent: *\nCrawl-delay: 10\nDisallow: /\nAllow: /search\n")
  self.assertTrue(allowed);self.assertEqual(delay,10)
 def test_zero_result_page(self):
  total,papers=parse_riss_html('<div class="srchResultListW"><div class="noResultW"><p>검색결과가 없습니다.</p></div></div>')
  self.assertEqual(total,0);self.assertEqual(papers,[])

if __name__=="__main__":unittest.main()
