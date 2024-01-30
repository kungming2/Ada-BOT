#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import copy
import datetime
import logging
import os
import re
import sys
import time
import traceback
from types import SimpleNamespace

import praw
import prawcore
import yaml
from profanity_check import predict

"""DEFINING VARIABLES"""

KEYWORD = "ADA"  # Ban keyword to pick up on.
SOURCE_FOLDER = os.path.dirname(os.path.realpath(__file__))
FILE_PATHS = {
    "auth": "/_auth.yaml",
    "error": "/_error.md",
    "logs": "/_logs.md",
}
for file_type in FILE_PATHS:
    FILE_PATHS[file_type] = SOURCE_FOLDER + FILE_PATHS[file_type]
FILE_ADDRESS = SimpleNamespace(**FILE_PATHS)
REDDIT = None
AUTH = None


"""LOGGER SETUP"""

# Set up the logger. By default, only display INFO or higher levels.
log_format = "%(levelname)s: %(asctime)s - [Ada] %(message)s"
logging.basicConfig(format=log_format, level=logging.INFO)

# Set the logging time to UTC.
logging.Formatter.converter = time.gmtime
logger = logging.getLogger(__name__)

# Define the logging handler (the file to write to.)
# By default, only log INFO level messages or higher.
handler = logging.FileHandler(FILE_ADDRESS.logs, "a", "utf-8")
handler.setLevel(logging.INFO)

# Set the time format in the logging handler.
d = "%Y-%m-%dT%H:%M:%SZ"
handler.setFormatter(logging.Formatter(log_format, datefmt=d))
logger.addHandler(handler)

"""STARTUP FUNCTIONS"""


def load_information(file_address):
    """Function that takes information on login/OAuth access from an
    external YAML file and loads it as a dictionary. It also loads the
    settings as a dictionary. Both are returned in a tuple.

    :return: A tuple containing two dictionaries, one for authentication
             data and the other with settings.
    """
    with open(file_address, "r", encoding="utf-8") as f:
        loaded_data = yaml.safe_load(f.read())

    return loaded_data


def login():
    """A simple function to log in and authenticate to Reddit."""
    global REDDIT
    global AUTH

    AUTH = SimpleNamespace(**load_information(FILE_ADDRESS.auth))

    # Authenticate the main connection.
    REDDIT = praw.Reddit(
        client_id=AUTH.app_id,
        client_secret=AUTH.app_secret,
        password=AUTH.password,
        user_agent=AUTH.user_agent,
        username=AUTH.username,
    )
    logger.info(f"Startup: Activating {AUTH.user_agent} v{AUTH.version}.")
    logger.info(f"Startup: Logging in as u/{AUTH.username}.")

    return


def moderators_list(subreddit_list):
    """Gets a list of all moderators on a list of subreddits."""
    all_mods = []

    # Iterate through each subreddit and get their mods.
    for subreddit in subreddit_list:
        mod_list = [x.name for x in subreddit.moderator()]
        all_mods += mod_list

    # Remove duplicates
    all_mods = list(set(all_mods))

    return all_mods


def main_error_log(entry):
    """A function to save detailed errors to a log for later review.
    This is easier to check for issues than to search through the entire
    events log, and is based off of a basic version of the function
    used in Wenyuan/Ziwen.

    :param entry: The text we wish to include in the error log entry.
                  Typically, this is the traceback entry.
    :return: Nothing.
    """

    # Open the file for the error log in appending mode.
    # Then add the error entry formatted our way.
    with open(FILE_ADDRESS.error, "a+", encoding="utf-8") as f:
        error_date_format = datetime.datetime.utcnow().strftime("%Y-%m-%dT%I:%M:%SZ")
        entry = entry.replace("\n", "\n    ")  # Indent the code.
        f.write(f"\n---------------\n### {error_date_format} \n{entry}\n")

    return


"""USER REPORTING"""


def extract_domains(text):
    """Extract domains from text."""
    # Define the regex pattern for extracting domains from URLs
    url_pattern = re.compile(r"https?://(?:www\.)?([^]/)]+)")

    # Use findall to find all matches in the text
    domains = re.findall(url_pattern, text)

    # Return None if no domains are found
    return domains if domains else None


def removal_report(object_list):
    """
    Looks at a list of submissions or comments and determines how many
    of the objects have been removed by moderators.
    :param object_list: A list of Comment or Submission PRAW objects.
    :return:
    """
    removal_count = 0

    # We pass the comments and submissions so that their removed
    # status is apparent (this is not possible when viewing objects
    # directly via a username).
    full_list = [x.fullname for x in object_list]
    full_list = list(REDDIT.info(full_list))

    if full_list[0].fullname.startswith("t1"):
        object_kind = "comment"
    else:
        object_kind = "submission"

    # Go over the items. There are different ways to detect if a comment
    # or a submission has been removed.
    for item in full_list:
        if isinstance(item, praw.models.Comment):  # It's a comment.
            if "[removed]" in item.body:
                removal_count += 1
        else:  # It's a post.
            if item.removed_by_category:  # Not None if it's been removed.
                removal_count += 1

    percentage = round(removal_count / len(object_list) * 100, 2)
    conclusion = (
        f"{removal_count}/{len(object_list)} {object_kind}s "
        f"removed site-wide. ({percentage}%)"
    )

    return conclusion


def user_report(username):
    """
    Generates a report with useful information about a user after
    they've been banned.

    Note that the function will fail gracefully if the user is now
    suspended or shadow-banned.

    :param username: Username of a Redditor.
    :return: A Markdown-formatted report.
    """
    user = REDDIT.redditor(username)
    try:
        user_submissions = list(user.submissions.new())
    except prawcore.exceptions.Forbidden:
        return f"User u/{username} is likely already suspended."
    except prawcore.exceptions.NotFound:
        return f"User u/{username} is likely already shadow-banned."
    user_comments = list(user.comments.new(limit=250))
    user_created = int(user.created_utc)
    comments_dict = {}
    submissions_dict = {}
    linked_urls = []
    age_days = int((time.time() - user_created) / 86400)

    # User creation date.
    dt_object = datetime.datetime.utcfromtimestamp(user_created)
    formatted_date = dt_object.strftime("%Y-%m-%d")

    # Format a header with the basic information.
    header = (
        f"#### u/{username}\n\n",
        f"* Submission Karma: {user.link_karma:,}\n",
        f"* Examined Submissions: {len(user_submissions)}/100\n",
        f"* Comment Karma: {user.comment_karma:,}\n",
        f"* Examined Comments: {len(user_comments)}/250\n",
        f"* Account Age: {age_days:,} days (created {formatted_date})\n",
        f"* Verified Email: {user.has_verified_email}\n\n",
    )
    header = "".join(header)

    # Examine the user's most commonly posted subreddits.
    if len(user_submissions) != 0:
        submission_section = (
            "\n#### Submissions\n\n| Subreddit | Count |\n|-----------|-------|"
        )
        total_sub_subreddits = [x.subreddit.display_name for x in user_submissions]
        for subreddit in total_sub_subreddits:
            submissions_dict[subreddit] = total_sub_subreddits.count(subreddit)
        for key in sorted(submissions_dict, key=submissions_dict.get, reverse=True)[
            :10
        ]:
            submission_line = f"\n| r/{key} | {submissions_dict[key]} |"
            submission_section += submission_line

        removal_submission_data = removal_report(user_submissions)
        submission_section += f"\n\n*{removal_submission_data}*\n\n"
    else:
        submission_section = ""

    # Examine the user's posted URLs.
    for submission in user_submissions:
        if not submission.is_self:  # This is a link post.
            match = extract_domains(submission.url)
            if match:
                linked_urls += match

    # Examine the user's most actively commented on subreddits.
    if len(user_comments) != 0:
        comment_section = (
            "\n#### Comments\n\n| Subreddit | Count |\n|-----------|-------|"
        )
        total_subreddits = [x.subreddit.display_name for x in user_comments]
        for subreddit in total_subreddits:
            comments_dict[subreddit] = total_subreddits.count(subreddit)
        for key in sorted(comments_dict, key=comments_dict.get, reverse=True)[:10]:
            comment_line = f"\n| r/{key} | {comments_dict[key]} |"
            comment_section += comment_line

        removal_comment_data = removal_report(user_comments)
        comment_section += f"\n\n*{removal_comment_data}*\n\n"
    else:
        comment_section = ""

    # Profanity and URL check.
    profanity_number = 0
    profanity_comments = []
    for comment in user_comments:
        # Check for profanity.
        comment_score = predict([comment.body])
        if comment_score == 1:
            profanity_number += 1
            if len(comment.body) > 200:
                body_formatted = comment.body.replace("\n", " ")[:200] + "..."
            else:
                body_formatted = comment.body.replace("\n", " ")
            comment_line = f"{body_formatted} (*[Link]({comment.permalink}) on r/{comment.subreddit}*)"
            profanity_comments.append(comment_line)
        # Check for URLs.
        url_present = extract_domains(comment.body)
        if url_present:
            linked_urls += url_present

    # Format the profanity section if necessary.
    if profanity_number:
        profanity_section = (
            f"\n**Profanity Score**: ({profanity_number}/{len(user_comments)})\n\n"
        )
        if profanity_number != 0:
            profanity_quotes = "\n> ".join(profanity_comments)
            profanity_section += f"\n> {profanity_quotes}"
    else:
        profanity_section = ""

    # Format the linked URLs section if necessary.
    # Exclude Reddit links. We only want external ones.
    linked_urls = [
        url for url in linked_urls if "redd.it" not in url and "reddit.com" not in url
    ]
    if linked_urls:
        url_dict = {}
        linked_section = (
            f"\n**Linked External Domains**:\n\n| Domain | Count |\n|--------|-------|"
        )

        for subreddit in linked_urls:
            url_dict[subreddit] = linked_urls.count(subreddit)
        for key in sorted(url_dict, key=url_dict.get, reverse=True)[:10]:
            url_line = f"\n| `{key}` | {url_dict[key]} |"
            linked_section += url_line
    else:
        linked_section = ""

    # Format everything.
    body = f"{header} {submission_section} {comment_section} {profanity_section} {linked_section}"
    footer = (
        "\n\n---\n\n",
        "[Report for Spam](https://www.reddit.com/report?reason=this-is-spam) • ",
        "[Ban Evasion](https://www.reddit.com/report?reason=its-ban-evasion) • ",
        "[Abuse](https://www.reddit.com/report?reason=its-promoting-hate-based-on-identity-or-vulnerability) • ",
        "[Violence](https://www.reddit.com/report?reason=it-threatens-violence-or-physical-harm)",
    )
    body += "".join(footer)

    return body


"""BAN LIST MANAGEMENT"""


def retrieve_recent_bans(subreddit, ada_specific=False):
    """Retrieve the list of users banned from a given subreddit.
    Returns a dictionary with Redditor objects and the note."""
    recently_banned = {}

    for username in REDDIT.subreddit(subreddit).banned():
        if ada_specific:
            if KEYWORD in username.note:
                recently_banned[str(username)] = username.note
        else:
            recently_banned[str(username)] = username.note

    return recently_banned


def are_dictionaries_different(dict1, dict2):
    """Simple function to assess differences between two dictionaries."""
    keys1 = set(dict1.keys())
    keys2 = set(dict2.keys())

    # Check if keys are different
    if keys1 != keys2:
        return True

    # Check if values are different for each key
    for key in keys1:
        if dict1[key] != dict2[key]:
            return True

    # If no differences are found, the dictionaries are the same
    return False


def wiki_template_creator(subreddit_object):
    """Creates a config page on the wiki if it doesn't already exist."""
    wiki_template = "    full_bans: null\n    ignore: null\n    soft_bans: null"

    # Wikipage where the data is stored.
    wiki_page = subreddit_object.wiki.create(
        name="ada_config", content=wiki_template, reason="Creating ADA config page."
    )

    return wiki_page


def retrieve_main_ban_list(username, ban_type="soft", retrieve=False):
    """
    Fetch the main ban list from the wiki page on which it is stored.

    :param username: Username we want to check.
    :param ban_type: soft or full - allows for different logic to be
                     applied to a different subset of users. Currently,
                     only full is implemented.
    :param retrieve: True puts it in a read-only mode to fetch the ban
                     list.
    :return:
    """
    # Wikipage where the data is stored.
    wiki_page = REDDIT.subreddit(AUTH.wiki).wiki["ada_config"]
    try:
        processed_data = wiki_page.content_md
    except prawcore.exceptions.NotFound:  # The wiki page does not exist.
        processed_data = wiki_template_creator(REDDIT.subreddit(AUTH.wiki))

    # Convert YAML text into a Python dictionary.
    existing_data = yaml.safe_load(processed_data)
    new_data = copy.deepcopy(existing_data)

    # In rare cases where the configuration page has no data.
    if existing_data is None:
        return {}

    if retrieve:
        return existing_data

    # Otherwise, add the username to the dictionary.
    if ban_type == "soft":
        if username not in new_data["soft_bans"] and username not in new_data["ignore"]:
            new_data["soft_bans"].append(username)
    elif ban_type == "full":
        if username not in new_data["full_bans"] and username not in new_data["ignore"]:
            new_data["full_bans"].append(username)

    # Edit the wikipage if there's changed data.
    if are_dictionaries_different(existing_data, new_data):
        yaml_output = yaml.dump(new_data)
        # Add four spaces to each line of the YAML output,
        # to allow for code formatting when viewed.
        indented_yaml_output = "\n".join(
            ["    " + line for line in yaml_output.splitlines()]
        )
        try:
            wiki_page.edit(
                content=str(indented_yaml_output), reason=f"Updating with new data..."
            )
        except (
            prawcore.exceptions.Forbidden,
            prawcore.exceptions.TooLarge,
        ):  # The wikipage is full.
            message_subject = "[Notification] ada_config Wiki Page Full"
            message_content = (
                "[Please check it out and clear it.]"
                f"(https://www.reddit.com/r/{AUTH.wiki}/wiki/ada_config)"
            )
            logger.warning("Save_Wiki: The configuration wiki page is full.")
            REDDIT.subreddit(AUTH.wiki).message(message_subject, message_content)
        else:
            logger.info(f"Updated the wikipage with new information.")
    else:
        logger.debug("No change in the data to be stored on the wikipage.")

    return existing_data


def retrieve_original_ban(username, action_limit=25):
    """
    Fetch information about the original ban from the mod log. This
    allows for the bot to message the person who banned it originally
    and let them know the bans propagated throughout the subreddits.
    :param username: Username of the account that was banned.
    :param action_limit: Number of entries to search retroactively.
    :return:
    """
    ban_by = None
    ban_subreddit = None

    for log in REDDIT.subreddit("mod").mod.log(action="banuser", limit=action_limit):
        # Check for bans not performed by Ada.
        if AUTH.username not in log.mod.name:
            # If the username matches the ban, return the Redditor
            # object of the mod who banned them.
            if username in log.target_author:
                ban_by = log.mod
                ban_subreddit = log.subreddit
                break

    if ban_by:
        return ban_by, ban_subreddit
    else:
        return None


"""MAIN ROUTINE"""


def main_routine():
    """Main routine for the bot. The only function apart from logging
    in that needs to be run."""
    currently_banned = retrieve_main_ban_list(None, retrieve=True)
    ignore_list = currently_banned["ignore"]
    newly_banned = []
    logger.debug(f"The current ban list is: {currently_banned}")

    # Fetch the subreddits the bot monitors.
    monitored_subreddits = REDDIT.redditor(AUTH.username).moderated()
    all_mods = moderators_list(monitored_subreddits)  # Get list of mods
    num_subreddits = len(monitored_subreddits)
    logger.info(f"{num_subreddits} subreddits to monitor.")

    # Fetch the recent bans in these subreddits.
    for subreddit in monitored_subreddits:
        index_num = list(monitored_subreddits).index(subreddit) + 1
        logger.info(
            f"({index_num}/{num_subreddits}) "
            f"Now assessing r/{subreddit.display_name}..."
        )
        recent_ada_bans = retrieve_recent_bans(
            subreddit.display_name, ada_specific=True
        )
        recent_sub_bans = retrieve_recent_bans(
            subreddit.display_name, ada_specific=False
        )

        # Make sure any ADA-tagged accounts are put on the main list.
        for username in recent_ada_bans:
            if username not in all_mods:  # Make sure not to add a mod
                retrieve_main_ban_list(username, ban_type="full")

        # Compare the currently banned list with the master list.
        for banned_user in currently_banned["full_bans"]:
            # Check if they're on a list to be ignored.
            if banned_user in ignore_list:
                logger.info(f"> u/{banned_user} on ignore list.")
                continue

            # Ban the user if they're not already banned.
            if banned_user in recent_sub_bans.keys():
                logger.debug(
                    f"> u/{banned_user} already banned on r/{subreddit.display_name}."
                )
            else:
                logger.debug(
                    f"> u/{banned_user} will be banned on r/{subreddit.display_name}."
                )
                try:
                    subreddit.banned.add(
                        banned_user, ban_reason="Banned from ADA main list."
                    )
                except praw.exceptions.RedditAPIException:
                    logger.info(f"> u/{banned_user} no longer exists or is suspended.")
                else:
                    logger.info(
                        f"> u/{banned_user} BANNED on r/{subreddit.display_name}."
                    )
                    newly_banned.append(banned_user)

    # Take stock of who was banned.
    newly_banned = list(set(newly_banned))
    if newly_banned:
        for banned_user in newly_banned:
            # Check each username and find out who originally banned them.
            # This is adjusted to scale with how many subreddits currently
            # use the bot.
            banned_mod, banned_sub = retrieve_original_ban(
                banned_user, action_limit=num_subreddits * 6
            )
            # Message the original mod who applied the ban.
            report = user_report(banned_user)
            banned_mod.message(
                subject=f"[Notification] ADA ban applied for u/{banned_user} from r/{banned_sub}",
                message=f"The user u/{banned_user} has been added to the ADA list and "
                f"banned from {num_subreddits} subreddits.\n\n{report}",
            )
            logger.info(
                f">> Messaged u/{banned_mod} about the ban they made from r/{banned_sub}."
            )
    else:  # No one was banned this run.
        logger.debug(">> Nobody banned; no messages sent.")

    logger.info("Shutdown: Run completed.")

    return


if __name__ == "__main__":
    if len(sys.argv) > 1:  # Simply append any command line argument to test.
        print("### Entering testing mode.")
        login()
    else:
        try:
            try:
                login()
                main_routine()
            except Exception as e:
                error_entry = f"\n### {e} \n\n"
                error_entry += traceback.format_exc()
                logger.error(error_entry)
                main_error_log(error_entry)  # Write to the log.
        except KeyboardInterrupt:
            # Manual termination of the script with Ctrl-C.
            logger.info("Manual user shutdown via keyboard.")
            sys.exit()
