I want a module to generate the relevant predictive features for attrition. We already have a probability model for attrition. You can refer to the README.md as well as the attrition model in attrition.py in ./src/hr_data_generator. Most of the code should be there. 

I want a feature generator module that works on the raw tables itself. After the data/tables are generated. The purpose is to mimic a feature extraction/curation step that needs to be done on the raw tables. 

We can brainstorm together on whether this should be a bunch of SQL queries or a python script, but I am leaning towards using SQL queries. 

At the end of the planning phase, don't jump straight into implementation. Instead, save a feature_extraction_plan.md file for review. 