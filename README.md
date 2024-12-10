
<img src="static/images/logo.png" alt="LesionBank Logo" width="150">

# LesionBank

Welcome to the LesionBank repository! This project powers [LesionBank.org](http://lesionbank.org), built on the Django framework using the **Lithium** template.

## Getting Started

To get started with LesionBank, follow these steps:

1. **Install Dependencies**  
Run the following command to clone the repository and install the required packages:

   ```bash
   git clone https://github.com/JosephIsaacTurner/LesionBank.git
   cd LesionBank
   pip install -r requirements.txt
   ```
  
    Run the following command to start the django project:

    ```bash
    python manage.py runserver
    ```
2. **Set up asynchronous tasks for the analysis page**
For the analysis page to work, you'll need:
    - A running Redis server.
    - A Celery worker processing tasks.
    Assuming you're using MacOS, you can install Redis with Homebrew:    

    ```bash 
    brew install redis
    ```

    And to get things running (macOS):

    ```bash 
    brew services start redis
    nohup celery -A django_project worker --loglevel=info &
    ```

    To turn off redis and celery, run:

    ```bash
    brew services stop redis
    ps aux | grep celery | grep -v grep | awk '{print $2}' | xargs kill
    ```

    For Linux, you can stop the celery worker by running:

    ```bash
    brew services stop redis-server
    ps aux | grep celery | grep -v grep | awk '{print $2}' | xargs -r kill
    ```
3. **Think about the database backend**   

    If you are running locally in development mode, you can use the default SQLite database. This means:
    1. Go to django_project/settings.py
    2. Go to the DATABASES section
    3. Uncomment the lines for SQLite and comment out the lines for PostgreSQL
    4. Then, go to sqlalchemy_utils/db_session.py
    5. Uncomment the lines for SQLite and comment out the lines for PostgreSQL    

    The inverse is true if you are running in production mode. You will need to set up a PostgreSQL database and configure the settings accordingly.