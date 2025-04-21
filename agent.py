import csv
import io
import os
import sys
from browser_use.browser.context import BrowserContext
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import asyncio
import pyperclip
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import SecretStr, BaseModel

from browser_use import ActionResult, Agent, Controller
from browser_use.browser.browser import Browser, BrowserConfig
from typing import List

browser = Browser()

# Load environment variables
load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")

class Grant(BaseModel):
	id: int
	url: str
	funding: str
	deadline: str

class Grants(BaseModel):
	grants: List[Grant]

controller = Controller(output_model=Grants)

def save_grants_to_csv(grants: Grants, filename: str = "grants.csv"):
    with open(filename, mode='w', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        writer.writerow(["ID", "Link", "Funding", "Deadline"])
        for grant in grants.grants:
            writer.writerow([grant.id, grant.url, grant.funding, grant.deadline])

def is_google_sheet(page) -> bool:
	return page.url.startswith('https://docs.google.com/spreadsheets/')


@controller.registry.action('Google Sheets: Open a specific Google Sheet')
async def open_google_sheet(browser: BrowserContext, google_sheet_url: str):
	page = await browser.get_current_page()
	if not is_google_sheet(page):
		return ActionResult(error='Current page is not a Google Sheet')
	
	if page.url != google_sheet_url:
		await page.goto(google_sheet_url)
		await page.wait_for_load_state()
	if not is_google_sheet(page):
		return ActionResult(error='Failed to open Google Sheet, are you sure you have permissions to access this sheet?')
	return ActionResult(extracted_content=f'Opened Google Sheet {google_sheet_url}', include_in_memory=False)


@controller.registry.action('Google Sheets: Get the contents of the entire sheet')
async def get_sheet_contents(browser: BrowserContext):
	page = await browser.get_current_page()
	if not is_google_sheet(page):
		return ActionResult(error='Current page is not a Google Sheet')
	
	# select all cells
	await page.keyboard.press('Enter')
	await page.keyboard.press('Escape')
	await page.keyboard.press('ControlOrMeta+A')
	await page.keyboard.press('ControlOrMeta+C')

	extracted_tsv = pyperclip.paste()
	return ActionResult(extracted_content=extracted_tsv, include_in_memory=True)


@controller.registry.action('Google Sheets: Select a specific cell or range of cells')
async def select_cell_or_range(browser: BrowserContext, cell_or_range: str):
	page = await browser.get_current_page()
	if not is_google_sheet(page):
		return ActionResult(error='Current page is not a Google Sheet')

	await page.keyboard.press('Enter')  # make sure we dont delete current cell contents if we were last editing
	await page.keyboard.press('Escape')  # to clear current focus (otherwise select range popup is additive)
	await asyncio.sleep(0.1)
	await page.keyboard.press('Home')  # move cursor to the top left of the sheet first
	await page.keyboard.press('ArrowUp')
	await asyncio.sleep(0.1)
	await page.keyboard.press('Control+J')  # open the goto range popup
	await asyncio.sleep(0.2)
	await page.keyboard.type(cell_or_range, delay=0.05)
	await asyncio.sleep(0.2)
	await page.keyboard.press('Enter')
	await asyncio.sleep(0.2)
	await page.keyboard.press('Escape')  # to make sure the popup still closes in the case where the jump failed
	return ActionResult(extracted_content=f'Selected cell {cell_or_range}', include_in_memory=False)


@controller.registry.action('Google Sheets: Get the contents of a specific cell or range of cells')
async def get_range_contents(browser: BrowserContext, cell_or_range: str):
	page = await browser.get_current_page()
	if not is_google_sheet(page):
		return ActionResult(error='Current page is not a Google Sheet')

	await select_cell_or_range(browser, cell_or_range)

	await page.keyboard.press('ControlOrMeta+C')
	await asyncio.sleep(0.1)
	extracted_tsv = pyperclip.paste()
	return ActionResult(extracted_content=extracted_tsv, include_in_memory=True)


@controller.registry.action('Google Sheets: Clear the currently selected cells')
async def clear_selected_range(browser: BrowserContext):
	page = await browser.get_current_page()
	if not is_google_sheet(page):
		return ActionResult(error='Current page is not a Google Sheet')

	await page.keyboard.press('Backspace')
	return ActionResult(extracted_content='Cleared selected range', include_in_memory=False)


@controller.registry.action('Google Sheets: Input text into the currently selected cell')
async def input_selected_cell_text(browser: BrowserContext, text: str):
	page = await browser.get_current_page()
	if not is_google_sheet(page):
		return ActionResult(error='Current page is not a Google Sheet')

	await page.keyboard.type(text, delay=0.1)
	await page.keyboard.press('Enter')  # make sure to commit the input so it doesn't get overwritten by the next action
	await page.keyboard.press('ArrowUp')
	return ActionResult(extracted_content=f'Inputted text {text}', include_in_memory=False)


@controller.registry.action('Google Sheets: Batch update a range of cells')
async def update_range_contents(browser: BrowserContext, range: str, new_contents_tsv: str):
	page = await browser.get_current_page()
	if not is_google_sheet(page):
		return ActionResult(error='Current page is not a Google Sheet')

	await select_cell_or_range(browser, range)

	# simulate paste event from clipboard with TSV content
	await page.evaluate(f"""
		const clipboardData = new DataTransfer();
		clipboardData.setData('text/plain', `{new_contents_tsv}`);
		document.activeElement.dispatchEvent(new ClipboardEvent('paste', {{clipboardData}}));
	""")

	return ActionResult(extracted_content=f'Updated cell {range} with {new_contents_tsv}', include_in_memory=False)


# many more snippets for keyboard-shortcut based Google Sheets automation can be found here, see:
# - https://github.com/philc/sheetkeys/blob/master/content_scripts/sheet_actions.js
# - https://github.com/philc/sheetkeys/blob/master/content_scripts/commands.js
# - https://support.google.com/docs/answer/181110?hl=en&co=GENIE.Platform%3DDesktop#zippy=%2Cmac-shortcuts

# Tip: LLM is bad at spatial reasoning, don't make it navigate with arrow keys relative to current cell
# if given arrow keys, it will try to jump from G1 to A2 by pressing Down, without realizing needs to go Down+LeftLeftLeftLeft

sensitive_data = {'x_name': os.getenv("MYUSERNAME"), 'x_password': os.getenv("MYPASSWORD")}

initial_actions = [
	{'go_to_url': {'url': 'https://spin.infoedglobal.com'}},
	{'click_element': {'index': 7}},
    {'send_keys': {'keys': 'California State University, San Bernardino\n'}},
    {'click_element': {'index': 8}},
    {'click_element': {'index': 0}},
    {'send_keys': {'keys': sensitive_data['x_name']}},
    {'click_element': {'index': 1}},
    {'send_keys': {'keys': sensitive_data['x_password']}},
    {'send_keys': {'keys': '\n'}},
    {'wait': {'seconds' : 15}},
    {'click_element': {'index': 2}},
    {'wait': {'seconds' : 10}},
    {'click_element': {'index': 10}},
	{'click_element': {'index': 14}},
	{'send_keys': {'keys': 'Deadlines\n'}},
	{'click_element': {'index': 15}},
	{'send_keys': {'keys': 'Greater Than or Equal To\n'}},
]

async def main(search_prompt: str):
	async with await browser.new_context() as context:
		model = ChatGoogleGenerativeAI(model='gemini-2.0-flash-exp', api_key=SecretStr(os.getenv('GEMINI_API_KEY')))

		write = Agent(
			task=search_prompt,
			llm=model,
			initial_actions=initial_actions,
			sensitive_data=sensitive_data,
			browser_context=context,
			controller=controller,
		)
		result = await write.run()

		extract = Agent(
			task="""
				collect all the ID, Link, Funding, and Deadline for all the grants listed on the page
					Columns:
						A: ID
						B: Link
						C: Funding
						D: Deadline (YYYY-MM-DD)
			""",
			llm=model,
			browser_context=context,
			sensitive_data=sensitive_data,
			controller=controller,
		)
		result = await extract.run()
		results = result.final_result()

		if result:
			parsed: Grants = Grants.model_validate_json(results)
			save_grants_to_csv(parsed, "grants.csv")
			print('Printed results')
	
		else:
			print('No result')



if __name__ == '__main__':

	asyncio.run(main())
