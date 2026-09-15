# Amazon Mockup E‑Commerce

Welcome to the **Amazon Mockup E‑Commerce** project! This is a fully functional mockup e‑commerce application designed for students pursuing the Data Engineer certification [RNCP37172](https://www.francecompetences.fr/recherche/RNCP/37172/). It demonstrates end‑to‑end architecture using FastAPI, Streamlit, PostgreSQL, and Docker, giving you hands‑on experience building and deploying a modern web application.

---

## 🚀 Features

* **User Registration & Authentication**: Secure signup and login with hashed passwords.
* **Product Catalog**: Browse a selection of products retrieved from a PostgreSQL backend.
* **Shopping Cart**: Add items to your cart, adjust quantities, and view your cart contents.
* **Checkout & Orders**: Place an order, choose a payment method, and automatically generate order and shipment records.
* **Shipment Tracking**: Track the status, carrier, and estimated delivery date for each item in your order.
* **Dockerized Deployment**: Launch the entire stack (database, backend, frontend) with a single `docker-compose` command.

---

## 🔧 Prerequisites

* **Docker & Docker Compose** (v2.0+)
* **Python** (3.9+)
* **PostgreSQL** database (if you’d rather run it outside Docker)

---

## 💻 Getting Started

1. **Clone the repository**

   ```bash
   git clone https://github.com/your-org/amazon-mockup-e-commerce.git
   cd amazon-mockup-e-commerce
   ```

2. **Configure Environment**

   * Create a `.env` file in the project root.
   * Add your database connection string:

     ```env
     DATABASE_URL=postgresql://<username>:<password>@<host>:<port>/<dbname>
     ```

3. **Launch with Docker Compose**

   ```bash
   docker-compose up --build
   ```

   This will spin up three services:

   * **db**: PostgreSQL database with initial migrations applied.
   * **backend**: FastAPI application exposed on port **8000**.
   * **frontend**: Streamlit UI exposed on port **8501**.

4. **Explore the App**

   * Visit **[http://localhost:8501](http://localhost:8501)** to open the Streamlit storefront.
   * Use the Streamlit UI to sign up, login (using a generated buyer ID), browse products, add to cart, and checkout.

---

## 📂 Project Structure

```plaintext
├── backend
│   ├── app
│   │   ├── database.py       # SQLAlchemy setup
│   │   ├── models.py         # ORM models
│   │   ├── schemas.py        # Pydantic schemas
│   │   ├── crud.py           # Business logic
│   │   └── main.py           # FastAPI entrypoint
│   └── Dockerfile
├── streamlit_app.py          # Streamlit frontend
├── docker-compose.yml        # Multi‑container setup
├── requirements.txt          # Python dependencies
└── README.md                 # This file
```

---

## ⚙️ Environment Variables

| Name           | Description                            |
| -------------- | -------------------------------------- |
| `DATABASE_URL` | Connection string to your Postgres DB. |

---

## 🤝 Contributing

Contributions are welcome! Whether you spot a bug, have an improvement, or just want to experiment:

1. Fork the repository.
2. Create a new branch: `git checkout -b feature/my-awesome-feature`.
3. Commit your changes: `git commit -m "Add my awesome feature"`.
4. Push to your branch: `git push origin feature/my-awesome-feature`.
5. Open a Pull Request and describe your changes.

---

## 📄 License

This project is released under the MIT License. See [LICENSE](LICENSE) for details.

---

*Happy coding and good luck with your certification!*
