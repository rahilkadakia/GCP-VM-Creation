# Steps to Run the Code:

1. Install Google Cloud SDK Shell on your machine.
2. Run "gcloud init", and set up the authentication configuration.
3. You can generate a public and private RSA key pair using "ssh-keygen" command (make sure SSH is installed on machine).
4. Make sure you store the private RSA key in the same directory as the code, and name it as "id_rsa".
5. Store this public key in the Metadata Section of Google Compute Engine.
6. Install dependencies using "pip install -r requirements.txt".
7. Run code using "python rnk9684_HW2.py".
8. You can change configuration of VM instance by passing in the relevant arguments in the defined function.