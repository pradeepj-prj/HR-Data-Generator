import numpy as np
from datetime import date, timedelta
import random
import pandas as pd

def get_age_gender(employee_data: dict): 
    age = np.random.randint(low=employee_data["age_min"], high=employee_data["age_max"])

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
    if roll < 0.9: 
        emp_type = "Full time"
    elif roll < 0.95: 
        emp_type = "Contract"
    else: 
        emp_type = "Part time"

    country = random.choice(employee_data["countries"])
    
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
    employees = {}
    for i in range(n): 
        age, gender = get_age_gender(employee_data)
        first_name, last_name = get_name(gender, employee_data)
        hiring_date = get_hiring_date(age)
        emp_type, country = get_emp_type_country(employee_data)
        employees[i+1] = {
            'age': age, 
            'gender': gender, 
            'first_name': first_name, 
            'last_name': last_name, 
            'hiring_date': hiring_date, 
            'country': country, 
            'employment_type': emp_type
        }
    
    return employees

def _get_assignment_proportions(n_assignments): 
    r_nums = np.array([np.random.rand() for _ in range(n_assignments)])
    r_nums_sum = r_nums.sum()
    r_num_norms = r_nums/r_nums_sum

    return list(r_num_norms)

def assign_employees_to_org(employees: dict, org_data: pd.DataFrame): 
    employee_assigments = []
    orgs = org_data["org_id"].to_list()
    t = date.today()
    for employee in employees.keys(): 
        num_assignments = random.choice([1, 2, 3, 4])
        props = _get_assignment_proportions(num_assignments)
        print(props)
        delta = t - employees[employee]["hiring_date"]
        s_date = employees[employee]["hiring_date"]
        for prop in props: 
            employee_assigment = {}
            employee_assigment["employee_id"] = employee
            employee_assigment["org_id"] = np.random.choice(orgs)
            employee_assigment["start_date"] = s_date
            e_date = s_date + prop*delta 
            employee_assigment["end_date"] = e_date
            s_date = e_date
            employee_assigments.append(employee_assigment)
    return employee_assigments
            
        


        
