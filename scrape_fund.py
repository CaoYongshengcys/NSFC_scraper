"""
使用Playwright自动化爬取青塔自科云基金项目数据
支持自定义关键词和年份范围
"""
from playwright.sync_api import sync_playwright
import csv
import json
import re
import time
import os
import argparse

def scrape_fund(keyword, start_year=2022, end_year=2026, login_wait=30):
    """
    爬取基金项目数据
    
    参数:
        keyword: 搜索关键词
        start_year: 起始年份
        end_year: 结束年份
        login_wait: 登录等待时间（秒）
    """
    all_projects = []
    seen_titles = set()  # 用于去重
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        
        # 尝试加载已保存的cookie
        cookie_file = 'cookies.json'
        if os.path.exists(cookie_file):
            with open(cookie_file, 'r') as f:
                cookies = json.load(f)
            context = browser.new_context()
            context.add_cookies(cookies)
            print("已加载保存的cookies")
        else:
            context = browser.new_context()
        
        page = context.new_page()
        page.set_default_timeout(60000)
        
        # 先访问首页
        print("正在访问首页...")
        page.goto("https://fund.cingta.com/", timeout=60000)
        time.sleep(3)
        
        print(f"请在浏览器中登录（如果需要），等待{login_wait}秒...")
        time.sleep(login_wait)
        
        # 保存cookies
        cookies = context.cookies()
        with open(cookie_file, 'w') as f:
            json.dump(cookies, f)
        print("已保存cookies")
        
        # 构建搜索URL
        search_url = f"https://fund.cingta.com/fund/list?keyword={keyword}&searchtype=(立项年份={start_year}-{end_year})"
        print(f"\n正在访问搜索页: {search_url}")
        page.goto(search_url, timeout=60000)
        
        # 等待页面加载
        print("等待搜索结果加载...")
        time.sleep(5)
        
        # 等待列表加载
        try:
            page.wait_for_selector('.list-item', timeout=30000)
            print("找到列表项!")
        except:
            print("等待列表超时，尝试其他选择器...")
            try:
                page.wait_for_selector('.result-list', timeout=10000)
            except:
                pass
        
        # 获取总项目数
        total_count = 0
        total_elem = page.query_selector('.result-message')
        if total_elem:
            total_text = total_elem.inner_text()
            print(f"结果信息: {total_text}")
            # 修复正则表达式，使其能匹配带逗号的数字
            total_match = re.search(r'项目数\s*([\d,]+)', total_text)
            if total_match:
                # 移除逗号并转换为整数
                total_count = int(total_match.group(1).replace(',', ''))
                print(f"总项目数: {total_count}")
        else:
            # 尝试其他方式获取总项目数
            try:
                # 可能网站使用了不同的元素或格式
                total_text = page.inner_text()
                # 查找包含项目数的文本
                total_match = re.search(r'项目数\s*([\d,]+)', total_text)
                if total_match:
                    total_count = int(total_match.group(1).replace(',', ''))
                    print(f"从页面文本中找到总项目数: {total_count}")
            except Exception as e:
                print(f"无法获取总项目数: {e}")
        
        # 查找列表项
        items = page.query_selector_all('.list-item')
        print(f"找到 {len(items)} 个列表项")
        
        if len(items) == 0:
            print("未找到数据，请检查是否需要登录或关键词是否正确")
            browser.close()
            return []
        
        page_num = 1
        max_pages = 1000  # 增加最大页数
        retry_count = 0
        max_retries = 3
        
        while page_num <= max_pages:
            print(f"\n正在解析第 {page_num} 页...")
            
            # 等待页面稳定
            time.sleep(1)
            
            # 等待列表项出现
            try:
                page.wait_for_selector('.list-item', timeout=10000)
            except:
                print("等待列表项超时")
                if retry_count < max_retries:
                    retry_count += 1
                    print(f"重试 {retry_count}/{max_retries}...")
                    time.sleep(3)
                    continue
                else:
                    print("重试次数已达上限，退出")
                    break
            
            # 等待加载动画消失（如果有的话）
            try:
                page.wait_for_selector('.el-loading-mask', state='hidden', timeout=5000)
            except:
                pass
            
            items = page.query_selector_all('.list-item')
            print(f"当前页找到 {len(items)} 个项目")
            
            if len(items) == 0:
                if retry_count < max_retries:
                    retry_count += 1
                    print(f"未找到项目，重试 {retry_count}/{max_retries}...")
                    time.sleep(3)
                    page.reload()
                    time.sleep(3)
                    continue
                else:
                    print("重试次数已达上限，退出")
                    break
            
            # 重置重试计数
            retry_count = 0
            page_project_count = 0
            
            for item in items:
                project = {}
                
                # 获取标题
                title_elem = item.query_selector('.title')
                if title_elem:
                    title_text = title_elem.inner_text().strip()
                    title_text = re.sub(r'收藏.*$', '', title_text).strip()
                    project['title'] = title_text
                    
                    # 去重检查
                    if title_text in seen_titles:
                        continue
                    seen_titles.add(title_text)
                
                # 获取详细信息
                item_wrap = item.query_selector('.item-wrap')
                if item_wrap:
                    info_items = item_wrap.query_selector_all('.item')
                    for it in info_items:
                        text = it.inner_text().strip()
                        
                        if '受资机构' in text:
                            amount_match = re.search(r'(?:¥|金额[：:])\s*([\d.]+)\s*万元', text)
                            if amount_match:
                                project['amount'] = amount_match.group(1) + '万元'
                            inst_match = re.search(r'受资机构[：:]\s*(.+?)(?:\s*¥|\s*金额)', text)
                            if inst_match:
                                project['institution'] = inst_match.group(1).strip()
                        
                        if '负责人' in text:
                            pi_match = re.search(r'负责人[：:]\s*(.+?)\s*立项年份', text)
                            if pi_match:
                                project['pi'] = pi_match.group(1).strip()
                            year_match = re.search(r'立项年份[：:]\s*(\d{4})', text)
                            if year_match:
                                project['year'] = year_match.group(1)
                        
                        if '资助机构' in text:
                            funder_match = re.search(r'资助机构[：:]\s*(.+?)\s*申报领域', text)
                            if funder_match:
                                project['funder'] = funder_match.group(1).strip()
                            field_match = re.search(r'申报领域[：:]*\s*(.+?)$', text)
                            if field_match:
                                field = field_match.group(1).strip()
                                project['field'] = field if field != '--' else ''
                
                if project.get('title'):
                    all_projects.append(project)
                    page_project_count += 1
            
            print(f"本页新增 {page_project_count} 个项目，已收集 {len(all_projects)} 个项目")
            
            if total_count > 0 and len(all_projects) >= total_count:
                print("已收集所有项目")
                break
            
            # 查找下一页按钮
            next_btn = page.query_selector('.el-pagination .btn-next')
            if not next_btn:
                # 尝试其他选择器
                next_btn = page.query_selector('button.btn-next')
            if not next_btn:
                next_btn = page.query_selector('.el-pagination button:last-child')
            
            if not next_btn:
                print("找不到下一页按钮，退出")
                break
            
            is_disabled = next_btn.get_attribute('disabled')
            btn_class = next_btn.get_attribute('class') or ''
            if is_disabled is not None or 'is-disabled' in btn_class or 'disabled' in btn_class:
                print("已到达最后一页")
                break
            
            try:
                # 滚动到分页区域确保可见
                next_btn.scroll_into_view_if_needed()
                time.sleep(0.5)
                
                # 记录当前第一个项目的标题，用于检测页面是否真的翻页了
                first_item = page.query_selector('.list-item .title')
                old_first_title = first_item.inner_text() if first_item else ""
                
                # 点击下一页
                next_btn.click()
                page_num += 1
                
                # 等待页面变化
                time.sleep(2)
                
                # 等待新内容加载
                for _ in range(10):
                    time.sleep(0.5)
                    new_first_item = page.query_selector('.list-item .title')
                    new_first_title = new_first_item.inner_text() if new_first_item else ""
                    if new_first_title and new_first_title != old_first_title:
                        break
                else:
                    print("页面内容未变化，可能翻页失败")
                    # 额外等待
                    time.sleep(2)
                
            except Exception as e:
                print(f"点击下一页失败: {e}")
                if retry_count < max_retries:
                    retry_count += 1
                    print(f"重试 {retry_count}/{max_retries}...")
                    time.sleep(3)
                    continue
                else:
                    break
        
        browser.close()
    
    return all_projects


def save_to_csv(projects, keyword, start_year, end_year):
    """保存数据到CSV文件"""
    if not projects:
        print("没有数据可保存")
        return
    
    # 生成文件名
    output_file = f'fund_{keyword}_{start_year}-{end_year}.csv'
    
    with open(output_file, 'w', encoding='utf-8-sig', newline='') as f:
        fieldnames = ['title', 'institution', 'pi', 'funder', 'amount', 'year', 'field']
        header_names = {
            'title': '题目', 
            'institution': '受资机构', 
            'pi': '负责人', 
            'funder': '资助机构', 
            'amount': '金额', 
            'year': '立项年份', 
            'field': '申报领域'
        }
        writer = csv.writer(f)
        writer.writerow([header_names[fn] for fn in fieldnames])
        for p in projects:
            writer.writerow([
                p.get('title', ''),
                p.get('institution', ''),
                p.get('pi', ''),
                p.get('funder', ''),
                p.get('amount', ''),
                p.get('year', ''),
                p.get('field', '')
            ])
    
    print(f"数据已保存到 {output_file}")
    return output_file


def main():
    parser = argparse.ArgumentParser(description='青塔自科云基金项目爬虫')
    parser.add_argument('-k', '--keyword', type=str, default='电动汽车',
                        help='搜索关键词 (默认: 电动汽车)')
    parser.add_argument('-s', '--start-year', type=int, default=2022,
                        help='起始年份 (默认: 2022)')
    parser.add_argument('-e', '--end-year', type=int, default=2026,
                        help='结束年份 (默认: 2026)')
    parser.add_argument('-w', '--wait', type=int, default=30,
                        help='登录等待时间秒数 (默认: 30)')
    
    args = parser.parse_args()
    
    print("="*50)
    print("青塔自科云基金项目爬虫")
    print("="*50)
    print(f"关键词: {args.keyword}")
    print(f"年份范围: {args.start_year} - {args.end_year}")
    print(f"登录等待: {args.wait}秒")
    print("="*50)
    
    # 爬取数据
    projects = scrape_fund(
        keyword=args.keyword,
        start_year=args.start_year,
        end_year=args.end_year,
        login_wait=args.wait
    )
    
    # 保存数据
    print(f"\n总共收集到 {len(projects)} 个项目")
    if projects:
        save_to_csv(projects, args.keyword, args.start_year, args.end_year)


if __name__ == '__main__':
    main()
