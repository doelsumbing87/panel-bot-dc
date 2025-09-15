# Discord Bot Control Panel

A modern, responsive web-based control panel for managing and monitoring your Discord bots in real-time. This panel provides a user-friendly interface to handle configurations, view live activity, and manage bot accounts without needing direct server access.
<img width="1325" height="791" alt="image" src="https://github.com/user-attachments/assets/d8fbecfd-908e-44bb-b9c5-89f8f75abc40" />

---

## Key Features

- **Real-time Monitoring:** Keep track of all bot accounts and their operational status (online, offline, or error) at a glance.
- **Account Management:** View detailed information for each connected bot account, including username, user ID, and last activity.
- **Live Log Viewer:** A real-time stream of system and bot activities, including sent messages, errors, and status changes, delivered directly to the web interface.
- **Web-based Configuration:** Edit the bot's `config.json` file directly from the panel, allowing for on-the-fly adjustments without restarting the application.
- **Dynamic Message Management:** Add, remove, and update the list of local messages (`pesan.txt`) that the bot uses for automated chatting.
- **Responsive Design:** The interface is fully responsive and accessible on both desktop and mobile devices.
- **Modern Interface:** A clean and intuitive dark theme designed for ease of use.
- **Real-time Updates:** Powered by WebSockets to ensure that all data on the dashboard is updated instantly without needing to refresh the page.

---

## Installation and Setup

Follow these steps to get the bot panel up and running on your local machine.

### 1. Clone the Repository
First, clone this repository to your local machine.
```bash
git clone [https://github.com/doelsumbing87/panel-bot-dc.git](https://github.com/doelsumbing87/panel-bot-dc.git)
cd panel-bot-dc
````

### 2\. Set Up a Virtual Environment

It's highly recommended to use a virtual environment to manage project dependencies.

**Windows:**

```bash
python -m venv venv
venv\Scripts\activate
```

**macOS / Linux:**

```bash
python3 -m venv venv
source venv/bin/activate
```

### 3\. Install Dependencies

Install all the required Python packages using the `requirements.txt` file.

```bash
pip install -r requirements.txt
```

### 4\. Configure Environment Variables

The application requires environment variables for sensitive data.

  * Create a new file named `.env` in the root directory of the project.
  * Copy the following content into the `.env` file and replace the placeholder values with your actual tokens and keys.

<!-- end list -->

```env
# Your Discord bot tokens, separated by commas if you have more than one.
DISCORD_TOKENS='YOUR_DISCORD_TOKEN_1,YOUR_DISCORD_TOKEN_2'

# Your Google API keys, separated by commas.
GOOGLE_API_KEYS='YOUR_GOOGLE_API_KEY_1,YOUR_GOOGLE_API_KEY_2'
```

### 5\. Initial Configuration

Before the first run, ensure you have the following files in your project's root directory:

  * `config.json`: Manages bot behavior and channel settings. A default file will be created on the first run if one is not found. You will need to edit this file to add your specific Channel IDs.
  * `pesan.txt`: A text file where each line is a unique message for the bot's local chatter feature. Create an empty file if you don't have one.

-----

## Running the Application

Once the installation and configuration are complete, you can start the application with a single command:

```bash
python app.py
```


The web panel will be accessible at **http://localhost:5000** in your web browser.

