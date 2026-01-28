import numpy as np
from datetime import date, timedelta
import random
import pandas as pd

def get_age_gender(employee_data: dict): 
    age = np.random.normal(loc=employee_data["age_mean"], scale=employee_data["age_spread"])
    age = int(age)

    gender_roll = np.random.rand()
    if gender_roll < employee_data["prob_neutral"]: 
        gender = "na"
    elif gender_roll < employee_data["prob_female"]:
        gender = "female"
    else: 
        gender = "male"

    return age, gender

def get_emp_type_country(employee_data: dict): 
    roll = np.random.rand()
    if roll < employee_data["prob_full_time"]: 
        emp_type = "Full time"
    elif roll < employee_data["prob_contract"]: 
        emp_type = "Contract"
    else: 
        emp_type = "Part time"

    country = random.choice(employee_data["location_id"])
    
    return emp_type, country

def get_name(gender: str, employee_data: dict): 
    if gender == "female": 
        first_name_choices = employee_data["female_names"]
    elif gender == "male": 
        first_name_choices = employee_data["male_first_names"]
    else: 
        first_name_choices = employee_data["neutral_names"]
    
    first_name = random.choice(first_name_choices)
    last_name = random.choice(employee_data["male_last_names"])

    return first_name, last_name

def get_hiring_date(age): 
    today = date.today()
    start_year = today.year - age + 21
    if start_year > today.year: 
        return today 
    else: 
        start = date(start_year, 1, 1)
        end = today 
        delta = end - start
        hiring_date = start + timedelta(seconds=random.randint(0, int(delta.total_seconds())))

        return hiring_date
    
def generate_employees(n, employee_data): 
    employees = []
    for i in range(n): 
        age, gender = get_age_gender(employee_data)
        first_name, last_name = get_name(gender, employee_data)
        hiring_date = get_hiring_date(age)
        emp_type, country = get_emp_type_country(employee_data)
        employee = {
            'employee_id': f"{country}{i}",
            'age': age, 
            'gender': gender, 
            'first_name': first_name, 
            'last_name': last_name, 
            'hiring_date': hiring_date, 
            'location_id': country, 
            'employment_type': emp_type
        }
        employees.append(employee)
    
    return employees




            
        


        
