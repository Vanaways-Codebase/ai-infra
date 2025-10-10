#!/bin/bash
cd $HOME
gunicorn app.main:app 