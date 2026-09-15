# Amazon Database Design

This project implements the database for any e-commerce application. The design and requirements are based on Amazon's e-commerce website.   
The database was created from the ground-up, following the traditional process of:
* Requirements Collection
  * [Functional Requirements](https://github.com/JedhaBootcamp/amazon-database-design/blob/master/Requirements.pdf)
* ER / EER Diagram Creation
  * [EER Diagram](https://github.com/JedhaBootcamp/amazon-database-design/blob/master/EER%20Diagram.png)
* Mapping the EER Diagram to a Relational Schema Diagram
* Normalizing the Relational Schema to 3NF
  * [Relational Schema](https://github.com/JedhaBootcamp/amazon-database-design/blob/master/Schema%20Diagram.pdf)
* SQL Table Creation Statements
* Addition of foreign key constraints, CHECK clauses, NOT NULL constraints, DEFAULT values, and triggered actions on foreign keys
  * [Table Creation](https://github.com/JedhaBootcamp/amazon-database-design/blob/master/Database%20Creation%20Statements.sql)
* Development of relevant stored procedures using PL/SQL
  * [Procedures](https://github.com/JedhaBootcamp/amazon-database-design/blob/master/Procedures.sql)
* Development of relevant triggers using PL/SQL
  * [Triggers](https://github.com/JedhaBootcamp/amazon-database-design/blob/master/Triggers.sql)
* Notebook to fill data into the database based on the [amazon reviews dataset](https://amazon-reviews-2023.github.io/).
  * [Data Insertion Notebook](https://github.com/JedhaBootcamp/amazon-database-design/blob/main/amazon-data.ipynb)
